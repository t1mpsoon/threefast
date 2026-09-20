"""Визуальная проверка витрины: снимки, замеры, микро-интеракции.

Запуск: python -m tools.visual_check [базовый_URL]
Требует playwright и запущенный сервер приложения.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

# playwright импортируется внутри main(): без него модуль остаётся читаемым
# (константы вроде GUEST_NAMES нужны тестам, а браузер — только для снимков).
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
# Имена для проверки оформления: в демо-очереди не должно быть десятка клонов.
GUEST_NAMES = ["Айгерим", "Данияр", "Мадина", "Тимур", "Асель", "Ерасыл",
               "Камила", "Нурлан", "Жанна", "Арман", "Сабина", "Мирас"]
OUT = Path("shots")

PAGES = [
    ("places", "/"),
    ("menu", "/e/1/menu"),
    ("menu2", "/e/3/menu"),
    ("order", "/order"),
    ("login", "/login"),
    ("error", "/e/999999/menu"),
]

MEASURE = """() => {
  const root = document.documentElement;
  const cs = getComputedStyle(document.documentElement);
  const flame = cs.getPropertyValue('--flame').trim().toLowerCase();
  const isFlame = (color) => {
    const m = color.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
    if (!m) return false;
    const hex = '#' + [m[1], m[2], m[3]]
      .map(n => Number(n).toString(16).padStart(2, '0')).join('');
    return hex === flame || hex === '#c6331a';
  };
  // Считаем видимые элементы, залитые акцентом: он должен быть системным.
  let flameSpots = 0;
  document.querySelectorAll('*').forEach(node => {
    const rect = node.getBoundingClientRect();
    if (rect.width < 6 || rect.height < 6) return;
    const style = getComputedStyle(node);
    if (isFlame(style.backgroundColor) || isFlame(style.color) ||
        isFlame(style.borderTopColor)) flameSpots++;
  });
  const card = document.querySelector('.place');
  const dish = document.querySelector('.dish');
  const dishGrid = document.querySelector('.dishes');
  const addBtn = document.querySelector('.add-btn');
  const h1 = document.querySelector('h1, .banner__name, .place__name');
  return {
    overflowX: root.scrollWidth - root.clientWidth,
    tokens: { flame: cs.getPropertyValue('--flame').trim(), muted: cs.getPropertyValue('--muted').trim() },
    flameSpots,
    font: h1 ? getComputedStyle(h1).fontFamily : getComputedStyle(document.body).fontFamily,
    plusJakarta: Array.from(document.fonts).some(f => f.family === 'Plus Jakarta Sans' && f.status === 'loaded'),
    cardRadius: card ? getComputedStyle(card).borderRadius : null,
    btnRadius: getComputedStyle(document.querySelector('.btn, .cartbar__inner') || document.body).borderRadius,
    places: document.querySelectorAll('.place').length,
    fastestFlag: document.querySelectorAll('.place__flag').length,
    placeSizes: Array.prototype.map.call(document.querySelectorAll('.place'),
      n => { const r = n.getBoundingClientRect();
             return Math.round(r.width) + 'x' + Math.round(r.height); }),
    promoPhoto: Boolean(document.querySelector('.promo__photo')),
    promoGradient: getComputedStyle(document.querySelector('.promo__veil') || document.body)
      .backgroundImage.includes('gradient'),
    photos: document.querySelectorAll('.place__photo, .dish__photo').length,
    badgeFree: document.querySelectorAll('.badge--free').length,
    badgeBusy: document.querySelectorAll('.badge--busy').length,
    badgeTime: document.querySelectorAll('.badge--time').length,
    /* Открыто ли хоть одно заведение: от этого зависит, есть ли бейдж времени. */
    anyOpen: Array.prototype.some.call(document.querySelectorAll('.badge--free, .badge--busy'),
                                       () => true),
    badgeRects: Array.prototype.map.call(document.querySelectorAll('.place__badges'),
      n => Math.round(n.getBoundingClientRect().left) + ':' + Math.round(n.getBoundingClientRect().bottom)),
    heroBadgeRect: (() => {
      const n = document.querySelector('.place--hero .place__badges');
      return n ? [Math.round(n.getBoundingClientRect().left) + ':' +
                  Math.round(n.getBoundingClientRect().bottom)] : null;
    })(),
    cartbarRadius: (() => {
      const n = document.querySelector('.cartbar__inner, .btn');
      return n ? getComputedStyle(n).borderRadius : null;
    })(),
    ratingPills: document.querySelectorAll('.place__rating').length,
    addBtnFlameIcon: Boolean(addBtn) &&
      getComputedStyle(addBtn).color.replace(/\\s/g, '') === 'rgb(255,79,50)',
    addBtnOnPhoto: Boolean(addBtn) && (() => {
      const media = addBtn.closest('.dish').querySelector('.dish__media');
      const a = addBtn.getBoundingClientRect(), m = media.getBoundingClientRect();
      const centre = a.top + a.height / 2;
      return centre > m.top && centre < m.bottom;
    })(),
    dishGridColumns: dishGrid ? getComputedStyle(dishGrid).gridTemplateColumns.split(' ').length : 0,
    dishCardWidth: dish ? Math.round(dish.getBoundingClientRect().width) : null,
    dishPhotoRatio: (() => {
      const img = document.querySelector('.dish__photo');
      if (!img) return null;
      const box = img.getBoundingClientRect();
      return box.height ? Number((box.width / box.height).toFixed(2)) : null;
    })(),
    priceSize: dish ? getComputedStyle(dish.querySelector('.dish__price')).fontSize : null,
    priceWeight: dish ? getComputedStyle(dish.querySelector('.dish__price')).fontWeight : null,
    descSize: dish && dish.querySelector('.dish__desc')
      ? getComputedStyle(dish.querySelector('.dish__desc')).fontSize : null,
    cartbar: document.querySelectorAll('.cartbar').length,
    sheets: document.querySelectorAll('.sheet').length,
    sheetsVisible: Array.prototype.filter.call(document.querySelectorAll('.sheet'),
      n => n.offsetHeight > 0 && getComputedStyle(n).display !== 'none').length,
    skeletons: document.querySelectorAll('.skeleton').length,
    noticesHost: Boolean(document.getElementById('notices'))
  };
}"""


def shoot(page, name: str, url: str, tag: str, wait: int = 900) -> dict:
    problems: list[str] = []
    failures: list[str] = []
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    # Ошибки времени выполнения: потерянная переменная не видна в node --check,
    # но ломает отрисовку целиком.
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    page.on("requestfailed", lambda r: failures.append(f"{r.url} ({r.failure})"))
    page.goto(f"{BASE}{url}", wait_until="networkidle")
    page.wait_for_timeout(wait)
    page.screenshot(path=str(OUT / f"{tag}-{name}.png"), full_page=True)
    data = page.evaluate(MEASURE)
    data["consoleErrors"] = problems
    data["requestFailures"] = failures
    return data


def main() -> int:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(exist_ok=True)
    problems: list[str] = []
    report: dict[str, dict] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch()

        for label, width, height, tag in (
            ("desktop", 1440, 950, "d"),
            ("mobile", 390, 844, "m"),
        ):
            context = browser.new_context(viewport={"width": width, "height": height})
            page = context.new_page()
            for name, url in PAGES:
                data = shoot(page, name, url, tag)
                report[f"{label}/{name}"] = data
                if data["overflowX"] > 2:
                    problems.append(f"{label}/{name}: горизонтальное переполнение {data['overflowX']}px")
                if data["requestFailures"]:
                    problems.append(f"{label}/{name}: не загрузилось {data['requestFailures']}")
                # Ошибка времени выполнения ломает экран даже без видимых признаков.
                console_errors = [
                    text for text in data["consoleErrors"]
                    # Страница ошибки сама отвечает 404 — это её смысл.
                    if not (name == "error" and "404" in text)
                ]
                if console_errors:
                    problems.append(f"{label}/{name}: ошибки в браузере {console_errors[:2]}")
                if name != "login" and not data["noticesHost"]:
                    problems.append(f"{label}/{name}: нет контейнера сообщений")
                if data["tokens"]["flame"] != "#FF4F32":
                    problems.append(f"{label}/{name}: акцент подменён ({data['tokens']['flame']})")
                if "Plus Jakarta Sans" not in (data["font"] or ""):
                    problems.append(f"{label}/{name}: шрифт не Plus Jakarta Sans ({data['font']})")
                if not data["plusJakarta"]:
                    problems.append(f"{label}/{name}: Plus Jakarta Sans не загрузился")
                if data["cardRadius"] and data["cardRadius"] != "20px":
                    problems.append(f"{label}/{name}: радиус карточки {data['cardRadius']}, ждём 20px")
                if name == "places":
                    if data["places"] < 2:
                        problems.append(f"{label}/places: карточек заведений {data['places']}")
                    if data["photos"] < 2:
                        problems.append(f"{label}/places: фото не отрисованы")
                    # Все карточки одинаковые: самое быстрое помечено бейджем.
                    sizes = data["placeSizes"]
                    if len(set(sizes)) > 1:
                        problems.append(f"{label}/places: карточки разного размера {sizes}")
                    if data["fastestFlag"] > 1:
                        problems.append(f"{label}/places: пометок «быстрее всего» {data['fastestFlag']}")
                    if not data["promoPhoto"] or not data["promoGradient"]:
                        problems.append(f"{label}/places: промо без фото-подложки или градиента")
                    if data["ratingPills"] < 2:
                        problems.append(f"{label}/places: рейтинг не оформлен капсулой")
                    # Бейджи одного типа карточек стоят на одной высоте.
                    rects = sorted(int(r.split(":")[1]) for r in set(data["badgeRects"]) if r)
                    if rects:
                        dominant = max(set(rects), key=rects.count)
                        odd = [value for value in rects if abs(value - dominant) > 4 and rects.count(value) > 1]
                        if odd:
                            problems.append(
                                f"{label}/places: бейджи обычных карточек на разной высоте {rects}"
                            )
                    if data["badgeTime"] < 1 and data["anyOpen"]:
                        problems.append(f"{label}/places: нет бейджа времени акцентом")
                if name == "menu":
                    if data["photos"] < 3:
                        problems.append(f"{label}/menu: фото блюд не отрисованы")
                    if data["cartbar"] != 1 or data["sheets"] != 2:
                        problems.append(f"{label}/menu: нет панели корзины или шторок")
                    if data["sheetsVisible"] != 0:
                        problems.append(
                            f"{label}/menu: шторки видны до открытия ({data['sheetsVisible']})"
                        )
                    # Бриф: на мобильном блюда в одну колонку, на десктопе — сетка.
                    want_columns = 1 if width < 600 else 2
                    if data["dishGridColumns"] < want_columns:
                        problems.append(
                            f"{label}/menu: колонок блюд {data['dishGridColumns']}, ждём {want_columns}"
                        )
                    if not data["addBtnOnPhoto"]:
                        problems.append(f"{label}/menu: кнопка «+» не наложена на фото")
                    if not data["addBtnFlameIcon"]:
                        problems.append(f"{label}/menu: иконка «+» не акцентного цвета")
                    if data["dishPhotoRatio"] and abs(data["dishPhotoRatio"] - 4 / 3) > 0.2:
                        problems.append(f"{label}/menu: фото блюда не 4:3 ({data['dishPhotoRatio']})")
                    if data["priceWeight"] and int(data["priceWeight"]) < 700:
                        problems.append(f"{label}/menu: цена не жирная ({data['priceWeight']})")
                    if data["descSize"] and data["priceSize"] and \
                            float(data["priceSize"][:-2]) <= float(data["descSize"][:-2]):
                        problems.append(f"{label}/menu: цена не крупнее описания")
                # На главных экранах витрины акцент обязан быть системным.
                if name in {"places", "menu"} and data["flameSpots"] < 4:
                    problems.append(
                        f"{label}/{name}: акцент встречается всего {data['flameSpots']} раз(а)"
                    )
                # Кнопки и панель действия капсульные — там, где они есть.
                if data["cartbarRadius"] and "999" not in data["cartbarRadius"]:
                    problems.append(
                        f"{label}/{name}: кнопка не капсула ({data['cartbarRadius']})"
                    )
            context.close()

        # ── Путь гостя: меню → шторка времени → шторка оформления → успех ──
        context = browser.new_context(viewport={"width": 390, "height": 844})
        page = context.new_page()
        flow_errors: list[str] = []
        page.on("console", lambda m: flow_errors.append(m.text) if m.type == "error" else None)

        page.goto(f"{BASE}/", wait_until="networkidle")
        page.wait_for_timeout(700)
        page.click(".place")
        page.wait_for_selector(".dish", timeout=10000)

        # Степпер: кнопка «+» превращается в «– 1 +».
        first_dish = page.eval_on_selector(".dish", "n => n.dataset.dish")
        page.click(f'.dish[data-dish="{first_dish}"] button[data-act="more"]')
        page.wait_for_timeout(400)
        report["flow/stepper"] = {
            "steppers": page.eval_on_selector_all(".stepper", "n => n.length"),
            "plusOne": page.eval_on_selector_all(".plus-one", "n => n.length"),
            "count": page.inner_text("#cart-count"),
            "cartbarUp": page.eval_on_selector("#cartbar", "n => n.classList.contains('is-up')"),
        }
        page.screenshot(path=str(OUT / "flow-1-menu.png"), full_page=True)

        # Панель корзины открывает шторку времени.
        page.click("#cart-open")
        page.wait_for_timeout(700)
        report["flow/sheet"] = page.evaluate("""() => ({
          open: document.getElementById('time-sheet').classList.contains('is-open'),
          visible: !document.getElementById('time-sheet').hidden,
          drums: document.querySelectorAll('.drum').length,
          slots: document.querySelectorAll('.slot').length,
          free: document.querySelectorAll('.slot:not([disabled])').length
        })""")

        if page.query_selector(".slot:not([disabled])") is None:
            page.click("#time-forward")
            page.wait_for_timeout(1200)

        free = page.query_selector(".slot:not([disabled])")
        if free is None:
            problems.append("flow: нет свободного слота даже на следующий день")
        else:
            free.click()
            page.wait_for_timeout(300)
            page.screenshot(path=str(OUT / "flow-2-time.png"))
            page.click("#time-confirm")
            page.wait_for_timeout(800)
            report["flow/checkout"] = page.evaluate("""() => ({
              open: document.getElementById('checkout-sheet').classList.contains('is-open'),
              summaryRows: document.querySelectorAll('#checkout-summary .summary__row').length,
              total: document.getElementById('checkout-total').textContent,
              when: document.getElementById('checkout-when').textContent,
              segments: document.querySelectorAll('.segment label').length
            })""")
            page.screenshot(path=str(OUT / "flow-3-checkout.png"))

            page.fill("#guest-name", random.choice(GUEST_NAMES))
            page.fill("#guest-phone", "+7 701 123 45 67")
            page.click("#checkout-submit")
            page.wait_for_selector(".success", timeout=15000)
            page.wait_for_timeout(900)
            page.screenshot(path=str(OUT / "flow-4-success.png"), full_page=True)
            report["flow/success"] = {
                "title": page.inner_text(".success h1"),
                "time": page.inner_text(".success__time"),
                "segments": page.eval_on_selector_all(".progress__seg", "nodes => nodes.length"),
                "states": page.eval_on_selector_all("[data-stop]", "nodes => nodes.map(n => n.getAttribute('data-state'))"),
                "share": page.eval_on_selector_all(".share-btn", "n => n.length"),
            }
            if "принят" not in report["flow/success"]["title"].lower():
                problems.append("flow: на экране успеха нет подтверждения заказа")
            if report["flow/success"]["segments"] != 4:
                problems.append("flow: в прогрессе не четыре сегмента")

        if flow_errors:
            problems.append(f"flow: ошибки в консоли {flow_errors}")
        context.close()

        # ── Движение и микро-состояния ─────────────────────────────────────
        motion_context = browser.new_context(viewport={"width": 390, "height": 844})
        motion_page = motion_context.new_page()
        motion: dict[str, object] = {}

        # Появление карточек: у каждой своя задержка.
        motion_page.goto(f"{BASE}/", wait_until="domcontentloaded")
        motion_page.wait_for_selector(".place", timeout=10000)
        motion_page.wait_for_timeout(60)
        motion["cardDelays"] = motion_page.eval_on_selector_all(
            ".place", "nodes => nodes.map(n => n.style.animationDelay || 'none')")
        motion["bannerClass"] = motion_page.eval_on_selector("#promo", "n => n.className")
        motion_page.wait_for_timeout(1200)

        # Скользящая плашка категории едет к новой вкладке.
        motion["pillBefore"] = motion_page.eval_on_selector("#chips-pill", "n => n.style.transform")
        chip_nodes = motion_page.query_selector_all(".chip")
        if len(chip_nodes) > 1:
            chip_nodes[1].click()
            motion_page.wait_for_timeout(400)
        motion["pillAfter"] = motion_page.eval_on_selector("#chips-pill", "n => n.style.transform")

        # Скелетон: у блика есть анимация.
        motion["skeletonShimmer"] = motion_page.evaluate("""() => {
          const host = document.createElement('div');
          document.body.appendChild(host);
          host.innerHTML = '<div class="skeleton" style="width:80px;height:40px"></div>';
          const after = getComputedStyle(host.firstChild, '::after');
          const running = after.animationName !== 'none' && after.animationDuration !== '0s';
          host.remove();
          return running;
        }""")

        motion_page.goto(f"{BASE}/e/1/menu", wait_until="domcontentloaded")
        motion_page.wait_for_selector(".dish", timeout=10000)
        motion["dishDelays"] = motion_page.eval_on_selector_all(
            ".dish", "nodes => nodes.slice(0, 3).map(n => n.style.animationDelay || 'none')")

        # Панель корзины: выезд с отскоком, прокрутка суммы, пульс числа позиций.
        motion_dish = motion_page.eval_on_selector(".dish", "n => n.dataset.dish")
        motion_page.click(f'.dish[data-dish="{motion_dish}"] button[data-act="more"]')
        motion_page.wait_for_timeout(60)
        motion["cartAnim"] = motion_page.eval_on_selector(
            "#cartbar", "n => getComputedStyle(n).animationName")
        motion["plusOne"] = motion_page.eval_on_selector_all(".plus-one", "n => n.length")
        mid = motion_page.inner_text("#cart-sum")
        motion_page.wait_for_timeout(500)
        end = motion_page.inner_text("#cart-sum")
        motion_page.click(f'.dish[data-dish="{motion_dish}"] button[data-act="more"]')
        motion_page.wait_for_timeout(80)
        nxt = motion_page.inner_text("#cart-sum")
        motion["odometer"] = {"mid": mid, "end": end, "next": nxt, "changed": mid != end or end != nxt}
        motion["countClass"] = motion_page.eval_on_selector("#cart-count", "n => n.className")

        # Шторка: отскок при открытии и подтверждение выбора слота.
        motion_page.click("#cart-open")
        motion_page.wait_for_timeout(500)
        motion["sheetAnim"] = motion_page.eval_on_selector(
            "#time-sheet", "n => getComputedStyle(n).animationName")
        if motion_page.query_selector(".slot:not([disabled])") is None:
            motion_page.click("#time-forward")
            motion_page.wait_for_timeout(1300)
        free_slot = motion_page.query_selector(".slot:not([disabled])")
        if free_slot:
            free_slot.click()
            motion_page.wait_for_timeout(60)
            motion["drumPicked"] = motion_page.evaluate("""() => ({
              hour: (document.querySelector('#hour-drum .slot.is-on') || {}).textContent || '',
              minute: (document.querySelector('#minute-drum .slot.is-on') || {}).textContent || '',
              confirm: (document.getElementById('time-confirm') || {}).textContent || ''
            })""")

        # Шторка закрывается свайпом вниз по ручке.
        grip = motion_page.query_selector("#time-sheet [data-drag]")
        if grip:
            box = grip.bounding_box()
            motion_page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            motion_page.mouse.down()
            motion_page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 260, steps=12)
            motion_page.mouse.up()
            motion_page.wait_for_timeout(700)
            motion["swipeClosed"] = motion_page.evaluate(
                "() => !document.getElementById('time-sheet').classList.contains('is-open')")
        # Блокировка прокрутки и счётчик открытых шторок.
        #
        # В обычном сценарии шторки взаимоисключающие: оформление закрывает
        # табло времени. Поэтому сначала проверяем именно это, а затем
        # открываем обе напрямую — так проверяем счётчик, ради которого он и
        # написан (закрытие нижней не должно возвращать прокрутку).
        # Состояние после свайпа: шторок нет, прокрутка свободна.
        motion["afterSwipe"] = motion_page.evaluate("""() => ({
          open: document.querySelectorAll('.sheet.is-open').length,
          count: window.Sheet.openCount(),
          overflow: document.body.style.overflow
        })""")
        if motion["afterSwipe"]["count"] != 0 or motion["afterSwipe"]["overflow"] != "":
            problems.append(f"шторки: после свайпа осталось {motion['afterSwipe']}")

        # Одна шторка: прокрутка закрыта, счётчик равен единице.
        motion["oneSheet"] = motion_page.evaluate("""() => {
          window.EP_SHEETS.forEach(sheet => sheet.close());
          window.EP_SHEETS[0].open();
          return {
            open: document.querySelectorAll('.sheet.is-open').length,
            count: window.Sheet.openCount(),
            overflow: document.body.style.overflow
          };
        }""")

        # Две шторки: счётчик два, прокрутка по-прежнему закрыта.
        motion_page.evaluate("() => window.EP_SHEETS[1].open()")
        # Класс is-open ставится в следующем кадре — ждём его перед замером.
        motion_page.wait_for_timeout(220)
        motion["twoSheets"] = motion_page.evaluate("""() => ({
          open: document.querySelectorAll('.sheet.is-open').length,
          count: window.Sheet.openCount(),
          overflow: document.body.style.overflow
        })""")

        # Закрываем верхнюю: прокрутка обязана остаться закрытой.
        motion_page.evaluate("() => window.EP_SHEETS[1].close()")
        motion_page.wait_for_timeout(220)
        motion["afterClosingTop"] = motion_page.evaluate("""() => ({
          open: document.querySelectorAll('.sheet.is-open').length,
          count: window.Sheet.openCount(),
          overflow: document.body.style.overflow
        })""")

        # Закрываем последнюю: только теперь прокрутка свободна.
        motion["afterClosingAll"] = motion_page.evaluate("""() => {
          window.EP_SHEETS[0].close();
          return {
            open: document.querySelectorAll('.sheet.is-open').length,
            count: window.Sheet.openCount(),
            overflow: document.body.style.overflow
          };
        }""")
        motion_page.wait_for_timeout(500)

        motion_context.close()

        report["motion"] = motion
        if len([d for d in motion["cardDelays"] if d != "none"]) < 2:
            problems.append("движение: у карточек нет последовательной задержки")
        if "enter" not in str(motion["bannerClass"]):
            problems.append("движение: баннер не участвует в появлении экрана")
        if motion["pillBefore"] == motion["pillAfter"]:
            problems.append("движение: плашка категории не переехала")
        if not motion["skeletonShimmer"]:
            problems.append("движение: у скелетона нет блика")
        if motion["cartAnim"] != "cart-up":
            problems.append(f"движение: панель корзины без отскока ({motion['cartAnim']})")
        if not motion["odometer"]["changed"]:
            problems.append("движение: сумма в панели не прокручивается")
        if "pulse" not in str(motion["countClass"]):
            problems.append("движение: число позиций не пульсирует")
        if motion["sheetAnim"] != "sheet-up":
            problems.append(f"движение: шторка без отскока ({motion['sheetAnim']})")
        picked = motion.get("drumPicked") or {}
        if not picked.get("hour") or not picked.get("minute"):
            problems.append(f"барабаны: значение не выбрано ({picked})")
        if "Подтвердить" not in str(picked.get("confirm", "")):
            problems.append("барабаны: кнопка подтверждения не готова")
        if not motion.get("swipeClosed", False):
            problems.append("движение: шторка не закрылась свайпом вниз")

        # Одна шторка: прокрутка закрыта.
        if motion.get("oneSheet"):
            if motion["oneSheet"]["count"] != 1 or motion["oneSheet"]["overflow"] != "hidden":
                problems.append(f"шторки: одна открытая — {motion['oneSheet']}")

        # Две шторки: счётчик два, прокрутка всё ещё закрыта.
        if motion.get("twoSheets"):
            if motion["twoSheets"]["count"] != 2:
                problems.append(f"шторки: счётчик при двух = {motion['twoSheets']['count']}")
            if motion["twoSheets"]["overflow"] != "hidden":
                problems.append("шторки: при двух открытых прокрутка не заблокирована")

        # Закрытие верхней не должно возвращать прокрутку под открытой нижней.
        if motion.get("afterClosingTop"):
            if motion["afterClosingTop"]["overflow"] != "hidden":
                problems.append(
                    "шторки: закрытие верхней вернуло прокрутку под открытой нижней"
                )
            if motion["afterClosingTop"]["count"] != 1:
                problems.append(
                    f"шторки: счётчик после верхней = {motion['afterClosingTop']['count']}"
                )

        if motion.get("afterClosingAll"):
            if motion["afterClosingAll"]["overflow"] != "":
                problems.append("шторки: после закрытия всех прокрутка осталась заблокированной")
            if motion["afterClosingAll"]["count"] != 0:
                problems.append(
                    f"шторки: счётчик после закрытия всех = {motion['afterClosingAll']['count']}"
                )

        # ── Отключение движения ────────────────────────────────────────────
        calm_context = browser.new_context(viewport={"width": 390, "height": 844},
                                           reduced_motion="reduce")
        calm_page = calm_context.new_page()
        calm_page.goto(f"{BASE}/", wait_until="networkidle")
        calm_page.wait_for_timeout(900)
        calm: dict[str, object] = {}
        calm["cardDelays"] = calm_page.eval_on_selector_all(
            ".place", "nodes => nodes.map(n => n.style.animationDelay || 'none')")
        calm["skeletonShimmer"] = calm_page.evaluate("""() => {
          const host = document.createElement('div');
          document.body.appendChild(host);
          host.innerHTML = '<div class="skeleton" style="width:80px;height:40px"></div>';
          const after = getComputedStyle(host.firstChild, '::after');
          const running = after.animationName !== 'none' && after.animationDuration !== '0s';
          host.remove();
          return running;
        }""")
        calm["placeTransition"] = calm_page.eval_on_selector(
            ".place", "n => getComputedStyle(n).transitionDuration")
        report["reducedMotion"] = calm
        if any(d != "none" for d in calm["cardDelays"]):
            problems.append("reduced-motion: карточки всё ещё появляются с задержкой")
        if calm["skeletonShimmer"]:
            problems.append("reduced-motion: блик скелетона продолжает идти")
        calm_context.close()

        # ── Наполнение главного экрана ─────────────────────────────────────
        home_context = browser.new_context(viewport={"width": 390, "height": 844})
        home_page = home_context.new_page()
        home_page.goto(f"{BASE}/", wait_until="networkidle")
        home_page.wait_for_timeout(1500)
        report["home"] = home_page.evaluate("""() => ({
          stats: document.querySelectorAll('.stat').length,
          quick: document.querySelectorAll('.quick__item').length,
          steps: document.querySelectorAll('.step-card').length,
          popular: document.querySelectorAll('.popular').length,
          tabbar: document.querySelectorAll('.tabbar__tab').length,
          pillWidth: document.getElementById('tabbar-pill').style.width,
          clock: (document.getElementById('live-clock') || {}).textContent || '',
          height: document.documentElement.scrollHeight,
          heroText: (document.querySelector('.place--hero .place__name') || {}).textContent || '',
          firstPopular: (document.querySelector('.popular__name') || {}).textContent || ''
        })""")
        home_page.screenshot(path=str(OUT / "home-mobile-top.png"))
        # Появление блоков при скролле: прокручиваем колесом, как это делает гость.
        for _ in range(8):
            home_page.mouse.wheel(0, 520)
            home_page.wait_for_timeout(300)
        home_page.mouse.wheel(0, 900)
        home_page.wait_for_timeout(1400)
        report["home"]["revealed"] = home_page.eval_on_selector_all(
            ".reveal.is-in", "nodes => nodes.length")
        # Считаем только блоки, которые реально показываются на странице.
        report["home"]["revealTotal"] = home_page.evaluate(
            "() => Array.from(document.querySelectorAll('.reveal'))"
            ".filter(n => !n.hidden).length")
        report["home"]["windowCard"] = home_page.evaluate(
            "() => !document.getElementById('window-card').hidden")
        report["home"]["windowCount"] = home_page.evaluate(
            "() => (document.getElementById('window-count') || {}).textContent || ''")
        report["home"]["tiles"] = home_page.eval_on_selector_all(".tile", "nodes => nodes.length")
        home_page.screenshot(path=str(OUT / "home-mobile-bottom.png"))
        home_context.close()

        desktop_context = browser.new_context(viewport={"width": 1440, "height": 1000})
        desktop_page = desktop_context.new_page()
        desktop_page.goto(f"{BASE}/", wait_until="networkidle")
        desktop_page.wait_for_timeout(1500)
        desktop_page.screenshot(path=str(OUT / "home-desktop.png"), full_page=True)
        report["homeDesktop"] = desktop_page.evaluate("""() => ({
          stats: document.querySelectorAll('.stat').length,
          popular: document.querySelectorAll('.popular').length,
          steps: document.querySelectorAll('.step-card').length,
          tabbarVisible: getComputedStyle(document.querySelector('.tabbar')).display,
          overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          height: document.documentElement.scrollHeight
        })""")

        # Переход между разделами, если браузер поддерживает View Transitions.
        report["viewTransitions"] = {
          "supported": desktop_page.evaluate("() => Boolean(document.startViewTransition)"),
          "marker": desktop_page.evaluate(
            "() => document.documentElement.classList.contains('has-view-transitions')")
        }
        desktop_context.close()
        browser.close()

    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                     encoding="utf-8")

    print("=== замеры ===")
    for key in ("desktop/places", "desktop/menu", "mobile/places", "mobile/menu"):
        if key in report:
            d = report[key]
            sizes = sorted(set(d.get("placeSizes") or []))
            print(f"{key}: переполнение={d['overflowX']}px, акцент встречается {d['flameSpots']} раз, "
                  f"карточек={d['places']}, размеры={sizes or '—'}, "
                  f"пометок «быстрее всего»={d.get('fastestFlag', 0)}, фото={d['photos']}, "
                  f"колонок блюд={d['dishGridColumns']}, цена={d['priceSize']}/{d['priceWeight']}, "
                  f"описание={d['descSize']}, радиус карточки={d['cardRadius']}")
    for key in ("flow/stepper", "flow/sheet", "flow/checkout", "flow/success"):
        if key in report:
            print(f"{key}: {report[key]}")
    if "motion" in report:
        m = report["motion"]
        print(f"движение: задержки карточек={m['cardDelays']}, блюда={m.get('dishDelays')}, "
              f"баннер={m['bannerClass']}, панель={m['cartAnim']}, шторка={m['sheetAnim']}, "
              f"сумма={m['odometer']}, слот подтверждён={m.get('slotConfirmed')}, "
              f"свайп={m.get('swipeClosed')}")
        print(f"шторки: после свайпа={m.get('afterSwipe')}, одна={m.get('oneSheet')}, "
              f"две={m.get('twoSheets')}")
        print(f"        после верхней={m.get('afterClosingTop')}, "
              f"после всех={m.get('afterClosingAll')}")
    if "reducedMotion" in report:
        r = report["reducedMotion"]
        print(f"reduced-motion: задержки={r['cardDelays']}, блик={r['skeletonShimmer']}, "
              f"переход={r['placeTransition']}")
    if "home" in report:
        h = report["home"]
        print(f"главная (телефон): шаги={h['steps']}, витрина={h['popular']}, "
              f"заведений={h.get('placesCount')}, вкладок={h['tabbar']}, "
              f"пилюля={h['pillWidth']}, часы={h['clock']}, высота={h['height']}px")
        print(f"   раскрыто при скролле: {h.get('revealed')} из {h.get('revealTotal')}, "
              f"окно выдачи: {h.get('windowCard')} {h.get('windowCount')}")
        print(f"   первое в витрине: {h['firstPopular']!r}")
        if h.get("revealTotal") and h.get("revealed") != h["revealTotal"]:
            problems.append(
                f"главная: при скролле раскрылось {h.get('revealed')} из {h.get('revealTotal')} блоков"
            )
        # Плитки кухонь убраны: проверяем, что они не вернулись.
        if h.get("tiles"):
            problems.append(f"главная: плитки кухонь вернулись ({h['tiles']})")
        if h.get("stats") or h.get("quick"):
            problems.append("главная: сводка или быстрые действия вернулись")
    if "homeDesktop" in report:
        d = report["homeDesktop"]
        print(f"главная (десктоп): витрина={d['popular']}, "
              f"шаги={d['steps']}, навигация={d['tabbarVisible']}, переполнение={d['overflowX']}px, "
              f"высота={d['height']}px")
        if d["overflowX"] > 2:
            problems.append(f"главная: переполнение {d['overflowX']}px")
        if d["tabbarVisible"] != "none":
            problems.append("главная: на десктопе осталась нижняя навигация")
    if "home" in report:
        h = report["home"]
        if h["steps"] != 3:
            problems.append(f"главная: шагов «как это работает» — {h['steps']}")
        if h["popular"] < 3:
            problems.append(f"главная: витрина блюд пуста ({h['popular']})")
        if h["tabbar"] != 3 or not h["pillWidth"]:
            problems.append("главная: нижняя навигация без индикатора")
        if h["height"] < 1800:
            problems.append(f"главная: экран всё ещё пустой ({h['height']}px)")

    print("\n=== снимки ===")
    for path in sorted(OUT.glob("*.png")):
        print(" ", path.name, f"{path.stat().st_size // 1024} КБ")

    print("\n=== проблемы ===")
    if problems:
        for problem in problems:
            print("  !", problem)
        return 1
    print("  не найдено")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
