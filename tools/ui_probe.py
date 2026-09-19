"""Сплошная проверка интерфейса: страницы, экраны, клавиатура, тач-цели.

Запуск:
    python -m tools.ui_probe             # все проверки
    python -m tools.ui_probe --quick     # только ошибки и переполнение

Инструмент не «смотрит глазами», а измеряет: размеры целей, переполнение по
горизонтали, порядок фокуса, тексты ошибок. Возвращает код 1, если нашёл
дефекты, — поэтому его можно ставить в общий прогон.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright  # noqa: E402

BASE = os.environ.get("EP_BASE_URL", "http://127.0.0.1:8000")
ADMIN = os.environ.get("EP_ADMIN_PASSWORD", "demo-pass-12345")
STAFF = os.environ.get("EP_STAFF_PASSWORD", "demo-pass-12345")

# Экраны, на которых проверяем вёрстку. Телефон — узкий и очень узкий,
# планшет и два настольных: так видно, где вёрстка ломается.
VIEWPORTS = [
    ("телефон 320", {"width": 320, "height": 568}),
    ("телефон 390", {"width": 390, "height": 844}),
    ("телефон 414", {"width": 414, "height": 896}),
    ("планшет 768", {"width": 768, "height": 1024}),
    ("ноутбук 1440", {"width": 1440, "height": 900}),
    ("монитор 1920", {"width": 1920, "height": 1080}),
]

problems: list[str] = []
notes: list[str] = []


def problem(text: str) -> None:
    problems.append(text)
    print(f"  ! {text}")


def ok(text: str) -> None:
    print(f"  + {text}")


# ── Сбор фактов со страницы ─────────────────────────────────────────────────
COLLECT = """() => {
  const doc = document.documentElement;
  const overflow = doc.scrollWidth - doc.clientWidth;

  /* Кликабельные элементы меньше удобного размера. */
  const small = [];
  document.querySelectorAll('button, a[href], input, select, [role="button"]').forEach(n => {
    const r = n.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return;
    const cs = getComputedStyle(n);
    if (cs.visibility === 'hidden' || cs.display === 'none' || cs.pointerEvents === 'none') return;
    if (n.closest('[hidden]')) return;
    /* Мелкие точки-индикаторы и подписи внутри строки — не цель нажатия. */
    if (cs.pointerEvents === 'none') return;
    if (r.height < 44 || r.width < 24) {
      small.push({
        tag: n.tagName.toLowerCase(),
        id: n.id || '',
        cls: (n.className || '').toString().slice(0, 40),
        text: (n.textContent || '').trim().slice(0, 24),
        w: Math.round(r.width), h: Math.round(r.height)
      });
    }
  });

  /* Иконки без подписи: у кнопки нет текста и нет aria-label. */
  const noName = [];
  document.querySelectorAll('button, a[href]').forEach(n => {
    const r = n.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return;
    if (n.closest('[hidden]')) return;
    const text = (n.textContent || '').trim();
    const label = n.getAttribute('aria-label') || n.getAttribute('title') || '';
    if (!text && !label) {
      noName.push({ id: n.id || '', cls: (n.className || '').toString().slice(0, 40) });
    }
  });

  /* Изображения без alt. */
  const noAlt = [];
  document.querySelectorAll('img').forEach(n => {
    if (!n.hasAttribute('alt')) noAlt.push(n.getAttribute('src') || '');
  });

  /* Заголовки по порядку. */
  const heads = Array.from(document.querySelectorAll('h1,h2,h3,h4'))
    .filter(n => n.getBoundingClientRect().height > 0)
    .map(n => Number(n.tagName.slice(1)));
  const jumps = [];
  for (let i = 1; i < heads.length; i++) {
    if (heads[i] - heads[i - 1] > 1) jumps.push(heads[i - 1] + '->' + heads[i]);
  }

  /* Элементы, вылезающие за правый край окна. */
  const wide = [];
  document.querySelectorAll('body *').forEach(n => {
    const r = n.getBoundingClientRect();
    if (r.width === 0) return;
    if (r.right > doc.clientWidth + 1) {
      const cs = getComputedStyle(n);
      if (cs.position === 'fixed') return;
      if (n.closest('[hidden]')) return;
      /* Внутри горизонтальной ленты элементы выходят за окно по замыслу:
         лента прокручивается. Проверяем только то, что торчит снаружи. */
      let scroller = n.parentElement, inside = false;
      while (scroller && scroller !== document.body) {
        const sc = getComputedStyle(scroller);
        if (sc.overflowX === 'auto' || sc.overflowX === 'scroll') { inside = true; break; }
        scroller = scroller.parentElement;
      }
      if (inside) return;
      wide.push({ tag: n.tagName.toLowerCase(), cls: (n.className || '').toString().slice(0, 40),
                  right: Math.round(r.right) });
    }
  });

  return {
    overflow, small, noName, noAlt, headJumps: jumps,
    wide: wide.slice(0, 8), wideCount: wide.length,
    title: document.title,
    lang: doc.getAttribute('lang') || ''
  };
}"""


def check_page(page, name: str, *, limits: dict | None = None) -> None:
    """Общие проверки любой страницы."""
    facts = page.evaluate(COLLECT)
    if facts["overflow"] > 1:
        problem(f"{name}: переполнение по горизонтали на {facts['overflow']}px")
    if facts["wideCount"]:
        sample = ", ".join(f"{w['cls'] or w['tag']}({w['right']})" for w in facts["wide"][:3])
        problem(f"{name}: {facts['wideCount']} элементов вылезают за окно — {sample}")
    if facts["noAlt"]:
        problem(f"{name}: изображения без alt — {facts['noAlt'][:3]}")
    if facts["headJumps"]:
        problem(f"{name}: пропуск уровня заголовка — {facts['headJumps']}")
    if not facts["lang"]:
        problem(f"{name}: у <html> нет атрибута lang")

    allow = (limits or {}).get("small_allow", [])
    small = [s for s in facts["small"] if s["id"] not in allow and s["cls"] not in allow]
    if small:
        sample = ", ".join(f"{s['id'] or s['cls']}({s['w']}×{s['h']})" for s in small[:5])
        problem(f"{name}: {len(small)} целей меньше 44px по высоте — {sample}")

    if facts["noName"]:
        sample = ", ".join(f"{n['id'] or n['cls']}" for n in facts["noName"][:4])
        problem(f"{name}: кнопки без доступного имени — {sample}")


def check_console(page, name: str, errors: list[str]) -> None:
    if errors:
        problem(f"{name}: ошибки в консоли — {errors[:2]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Проверка интерфейса ThreeFast")
    parser.add_argument("--quick", action="store_true", help="только ошибки и переполнение")
    args = parser.parse_args(argv)

    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ── Вёрстка на всех экранах ────────────────────────────────────────
        print("=== вёрстка по экранам ===")
        for label, viewport in VIEWPORTS:
            context = browser.new_context(viewport=viewport)
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

            for path, page_name in (("/", "главная"), ("/e/2/menu", "меню"),
                                    ("/login", "вход")):
                page.goto(f"{BASE}{path}", wait_until="networkidle")
                page.wait_for_timeout(1100)
                check_page(page, f"{label} / {page_name}")
                check_console(page, f"{label} / {page_name}", errors)
                errors.clear()
            context.close()
        ok(f"экранов проверено: {len(VIEWPORTS) * 3}")

        # ── Клавиатура: весь путь заказа без мыши ──────────────────────────
        print("=== клавиатура ===")
        context = browser.new_context(viewport={"width": 390, "height": 844})
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{BASE}/e/2/menu", wait_until="networkidle")
        page.wait_for_timeout(1200)

        # Первое блюдо должно добавляться с клавиатуры.
        page.keyboard.press("Tab")
        reached = []
        for _ in range(60):
            info = page.evaluate("""() => {
              const a = document.activeElement;
              return a ? { tag: a.tagName, id: a.id, cls: (a.className||'').toString().slice(0,30),
                           text: (a.textContent||'').trim().slice(0,20) } : null;
            }""")
            reached.append(info)
            if info and "add-btn" in info["cls"]:
                break
            page.keyboard.press("Tab")
        else:
            problem("клавиатура: кнопка добавления блюда недостижима по Tab")

        if reached and reached[-1] and "add-btn" in reached[-1]["cls"]:
            page.keyboard.press("Enter")
            page.wait_for_timeout(900)
            count = page.evaluate("() => (document.getElementById('cart-count')||{}).textContent || ''")
            if "1" not in count:
                problem(f"клавиатура: Enter на кнопке блюда не добавил позицию ({count!r})")
            else:
                ok("блюдо добавляется с клавиатуры")

        # Шторка: Escape должен закрывать, фокус — возвращаться.
        page.click("#cart-open")
        page.wait_for_timeout(1600)
        sheet_open = page.evaluate("() => document.getElementById('time-sheet').classList.contains('is-open')")
        if not sheet_open:
            problem("клавиатура: шторка времени не открылась")
        else:
            page.keyboard.press("Escape")
            page.wait_for_timeout(700)
            closed = page.evaluate("() => !document.getElementById('time-sheet').classList.contains('is-open')")
            if not closed:
                problem("клавиатура: Escape не закрывает шторку времени")
            focus_back = page.evaluate("() => document.activeElement ? document.activeElement.id : ''")
            if focus_back != "cart-open":
                problem(f"клавиатура: после Escape фокус не вернулся на кнопку (сейчас {focus_back!r})")
            else:
                ok("Escape закрывает шторку и возвращает фокус")

        # Ловушка фокуса: Tab внутри открытой шторки не должен уходить наружу.
        page.click("#cart-open")
        page.wait_for_timeout(1500)
        outside = 0
        for _ in range(40):
            page.keyboard.press("Tab")
            if page.evaluate("""() => {
              const a = document.activeElement;
              if (!a) return true;
              const sheet = document.getElementById('time-sheet');
              return !sheet.contains(a) && a !== document.body;
            }"""):
                outside += 1
        if outside:
            problem(f"клавиатура: фокус выходит из открытой шторки ({outside} раз из 40)")
        else:
            ok("фокус удерживается внутри шторки")
        check_console(page, "клавиатура", errors)
        context.close()

        # ── Панели: кухня и администратор ──────────────────────────────────
        print("=== панели ===")
        for user, password, target, name in (
            ("kitchen-bowl", STAFF, "/staff", "кухня"),
            ("demo_admin", ADMIN, "/staff", "админ заведения"),
        ):
            for label, viewport in (("телефон 390", {"width": 390, "height": 844}),
                                    ("ноутбук 1440", {"width": 1440, "height": 900})):
                context = browser.new_context(viewport=viewport)
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"{BASE}/login", wait_until="networkidle")
                page.fill("#username", user)
                page.fill("#password", password)
                page.click("button[type=submit]")
                page.wait_for_url(f"**{target}", timeout=20000)
                page.wait_for_timeout(1600)
                check_page(page, f"{name} {label} / очередь")
                for panel in page.evaluate(
                    "() => Array.from(document.querySelectorAll('.crew__tab')).map(t => t.dataset.panel)"
                ):
                    page.click(f'.crew__tab[data-panel="{panel}"]')
                    page.wait_for_timeout(1400)
                    check_page(page, f"{name} {label} / {panel}")
                check_console(page, f"{name} {label}", errors)
                context.close()

        # ── Узкий экран и крупный шрифт ────────────────────────────────────
        print("=== крупный системный шрифт ===")
        context = browser.new_context(viewport={"width": 390, "height": 844})
        page = context.new_page()
        page.goto(f"{BASE}/e/2/menu", wait_until="networkidle")
        page.add_style_tag(content="html { font-size: 21px !important; }")
        page.wait_for_timeout(1200)
        facts = page.evaluate(COLLECT)
        if facts["overflow"] > 1:
            problem(f"крупный шрифт: переполнение по горизонтали на {facts['overflow']}px")
        else:
            ok("при шрифте 21px вёрстка не разъезжается")
        context.close()

        browser.close()

    print("\n=== итог ===")
    if problems:
        print(f"найдено дефектов: {len(problems)}")
        for item in problems:
            print(f"  - {item}")
        return 1
    print("дефектов не найдено")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
