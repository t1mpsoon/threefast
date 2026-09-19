"""Снимки и замеры панели кухни и администратора.

Запуск:
    set EP_ADMIN_PASSWORD=... & set EP_STAFF_PASSWORD=...
    python -m tools.crew_shot

Проверяет, что на панели есть сводка смены, очередь, вкладки и меню,
и что на экране нет переполнения по горизонтали.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright  # noqa: E402

BASE = os.environ.get("EP_BASE_URL", "http://127.0.0.1:8000")
OUT = Path("shots")
ADMIN = os.environ.get("EP_ADMIN_PASSWORD", "")
STAFF = os.environ.get("EP_STAFF_PASSWORD", "")
KITCHEN_USER = os.environ.get("EP_KITCHEN_USER", "kitchen-bowl")

MEASURE = """() => ({
  stats: document.querySelectorAll('.crew__stat').length,
  tickets: document.querySelectorAll('.ticket').length,
  tabs: document.querySelectorAll('.crew__tab').length,
  panels: document.querySelectorAll('.crew__panel').length,
  menuCards: document.querySelectorAll('.menu-card').length,
  meters: document.querySelectorAll('.crew__stat-value').length,
  clock: document.querySelectorAll('#crew-clock').length,
  place: (document.getElementById('crew-place') || {}).textContent || '',
  pillWidth: (document.getElementById('crew-pill') || {}).style
    ? document.getElementById('crew-pill').style.width : '',
  overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth
})"""


def login(page, username: str, password: str) -> None:
    page.goto(f"{BASE}/login", wait_until="networkidle")
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("button[type=submit]")
    page.wait_for_url("**/staff", timeout=15000)


def main() -> int:
    if not ADMIN or not STAFF:
        print("нужны EP_ADMIN_PASSWORD и EP_STAFF_PASSWORD")
        return 2
    OUT.mkdir(exist_ok=True)
    problems: list[str] = []
    report: dict[str, object] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ── Кухня одного заведения ─────────────────────────────────────────
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{BASE}/login", wait_until="networkidle")
        page.screenshot(path=str(OUT / "crew-0-login.png"))

        login(page, KITCHEN_USER, STAFF)
        page.wait_for_timeout(1500)
        kitchen = page.evaluate(MEASURE)
        report["kitchen/queue"] = kitchen
        page.screenshot(path=str(OUT / "crew-1-kitchen-queue.png"), full_page=True)
        # Сводка-дашборд и часы убраны: очередь должна начинаться сразу.
        if kitchen["stats"]:
            problems.append(f"кухня: сводка смены вернулась ({kitchen['stats']})")
        if kitchen["tickets"] < 1:
            problems.append("кухня: очередь пуста — нечего показывать смене")
        # У кухни две вкладки: очередь и меню. Настройки и аналитика — у админа.
        if kitchen["tabs"] != 2:
            problems.append(f"кухня: вкладок {kitchen['tabs']}, ждём 2")
        if kitchen["overflowX"] > 2:
            problems.append(f"кухня: переполнение {kitchen['overflowX']}px")
        if not kitchen["place"]:
            problems.append("кухня: не показано заведение смены")

        # Кухня: меню только для чтения. Формы правки и кнопок быть не должно.
        page.click('.crew__tab[data-panel="menu"]')
        page.wait_for_timeout(1600)
        readonly = page.evaluate("""() => ({
          cards: document.querySelectorAll('.menu-card').length,
          badge: (document.querySelector('.menu-card__side .badge') || {}).textContent || '',
          buttons: document.querySelectorAll('.menu-card__side button').length,
          dishForm: document.querySelectorAll('#dish-form').length,
          dishNew: document.querySelectorAll('#dish-new').length,
          empty: Boolean(document.querySelector('#menu-body .empty')),
          emptyText: (document.querySelector('#menu-body .empty p') || {}).textContent || ''
        })""")
        report["kitchen/menuReadonly"] = readonly
        page.screenshot(path=str(OUT / "crew-2-kitchen-menu.png"), full_page=True)
        if readonly["empty"]:
            problems.append(f"кухня: меню не отрисовалось — {readonly['emptyText']}")
        if readonly["cards"] < 1:
            problems.append("кухня: меню пустое")
        if "просмотр" not in readonly["badge"]:
            problems.append(f"кухня: нет бейджа просмотра ({readonly['badge']!r})")
        if readonly["buttons"] or readonly["dishForm"] or readonly["dishNew"]:
            problems.append("кухня: доступны элементы правки меню")

        # Прокрученный вид: закреплённая шапка не должна наезжать на карточки.
        page.mouse.wheel(0, 520)
        page.wait_for_timeout(600)
        overlap = page.evaluate("""() => {
          const top = document.querySelector('.top').getBoundingClientRect();
          return Array.from(document.querySelectorAll('.menu-card'))
            .filter(n => { const r = n.getBoundingClientRect();
                           return r.top < top.bottom && r.bottom > top.top; }).length;
        }""")
        report["kitchen/headerOverlap"] = overlap
        page.screenshot(path=str(OUT / "crew-2b-kitchen-menu-scrolled.png"))
        if overlap:
            problems.append(f"кухня: шапка перекрывает {overlap} карточек меню")

        # Вкладок настроек и аналитики у кухни быть не должно: ручки закрыты админом.
        tabs = page.evaluate("""() => ({
          tabs: Array.from(document.querySelectorAll('.crew__tab')).map(t => t.dataset.panel),
          settingsPanel: document.querySelectorAll('[data-panel=settings]').length,
          reportPanel: document.querySelectorAll('[data-panel=report]').length,
          role: (document.getElementById('crew-role') || {}).textContent || ''
        })""")
        report["kitchen/tabs"] = tabs
        if "settings" in tabs["tabs"] or "report" in tabs["tabs"]:
            problems.append(f"кухня: лишние вкладки {tabs['tabs']}")
        if tabs["settingsPanel"] or tabs["reportPanel"]:
            problems.append("кухня: панели настроек или аналитики попали в разметку")
        if "Кухня" not in tabs["role"]:
            problems.append(f"кухня: не показан бейдж роли ({tabs['role']!r})")
        context.close()

        # ── Администратор: аналитика ───────────────────────────────────────
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        login(page, "demo_admin", ADMIN)
        page.wait_for_timeout(1200)
        admin_tabs = page.evaluate("() => document.querySelectorAll('.crew__tab').length")
        page.click('.crew__tab[data-panel="report"]')
        page.wait_for_timeout(1500)
        analytics = page.evaluate("""() => ({
          cards: document.querySelectorAll('.report__card').length,
          values: Array.from(document.querySelectorAll('.report__value'))
            .map(n => n.textContent.trim()),
          goals: document.querySelectorAll('.report__goal').length,
          bars: document.querySelectorAll('.report__bar span').length
        })""")
        report["admin/analytics"] = analytics
        page.screenshot(path=str(OUT / "crew-4-admin-analytics.png"), full_page=True)
        if analytics["cards"] < 4:
            problems.append(f"админ: карточек аналитики {analytics['cards']}")
        if analytics["goals"] < 2:
            problems.append("админ: не показано выполнение целей продукта")
        # Смена периода пересчитывает карточки (кликаем по подписи, как гость).
        page.click('.segment label:has(input[value="week"])')
        page.wait_for_timeout(1200)
        report["admin/weekChanged"] = page.evaluate(
            "() => document.querySelector('.report__value').textContent.trim()")
        page.screenshot(path=str(OUT / "crew-5-admin-week.png"), full_page=True)

        # Админ тоже видит очередь.
        page.click('.crew__tab[data-panel="queue"]')
        page.wait_for_timeout(1200)
        report["admin/queue"] = page.evaluate(MEASURE)
        page.screenshot(path=str(OUT / "crew-6-admin-queue.png"), full_page=True)
        if admin_tabs < 4:
            problems.append(f"админ: вкладок {admin_tabs}, ждём 4")

        # ── Телефон ────────────────────────────────────────────────────────
        mobile = browser.new_context(viewport={"width": 390, "height": 844})
        page = mobile.new_page()
        login(page, KITCHEN_USER, STAFF)
        page.wait_for_timeout(1400)
        phone = page.evaluate(MEASURE)
        report["kitchen/mobile"] = phone
        page.screenshot(path=str(OUT / "crew-7-kitchen-mobile.png"), full_page=True)
        if phone["overflowX"] > 2:
            problems.append(f"кухня (телефон): переполнение {phone['overflowX']}px")
        mobile.close()

        if errors:
            problems.append(f"ошибки в консоли: {errors[:3]}")
        browser.close()

    (OUT / "crew_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== панели ===")
    for key, value in report.items():
        print(f"  {key}: {value}")
    print("=== проблемы ===")
    if problems:
        for problem in problems:
            print(f"  ! {problem}")
    else:
        print("  не найдено")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
