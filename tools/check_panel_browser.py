"""Проверка сессии смены и навигации панелей в настоящих браузерах.

Что проверяем:
  1. вход с галочкой «запомнить меня» оставляет cookie на недели вперёд —
     планшет на кухне не просит логин каждую смену;
  2. на телефоне у смены ВИДНЫ ссылки разделов (у гостя там нижняя панель,
     а у панелей её нет — раньше навигация просто исчезала);
  3. есть кнопка выхода, и после неё панель снова закрыта;
  4. с вложенной страницы можно вернуться назад по явной ссылке.

Запуск: python -m tools.check_panel_browser [базовый_URL] [логин] [пароль]
Требует playwright и запущенный сервер приложения.
"""

from __future__ import annotations

import sys
import time

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
USERNAME = sys.argv[2] if len(sys.argv) > 2 else "staff"
PASSWORD = sys.argv[3] if len(sys.argv) > 3 else "staff-pass-123"

TOKEN_COOKIE = "ep_token"
PHONE = {"width": 390, "height": 844}

failures: list[str] = []
checks = 0


def check(label: str, condition: bool, extra: object = "") -> None:
    global checks
    checks += 1
    if condition:
        print(f"[OK  ] {label}")
    else:
        failures.append(label)
        print(f"[FAIL] {label}  -> {extra}")


def login(page, remember: bool) -> None:
    page.goto(f"{BASE}/login", wait_until="domcontentloaded")
    page.fill("#username", USERNAME)
    page.fill("#password", PASSWORD)
    box = page.locator("#remember")
    if box.is_checked() != remember:
        box.click()
    page.click("#login-button")
    page.wait_for_url(lambda url: "/login" not in url, timeout=20_000)


def run_engine(engine, title: str) -> None:
    print(f"\n── {title} ──")
    browser = engine.launch()
    context = browser.new_context(viewport=PHONE)
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on(
        "console",
        lambda msg: errors.append(msg.text) if msg.type == "error" else None,
    )

    # 1. Вход с «запомнить меня»: cookie живёт недели.
    login(page, remember=True)
    check(f"{title}: после входа попали в панель", "/staff" in page.url or "/super" in page.url, page.url)

    cookies = {cookie["name"]: cookie for cookie in context.cookies()}
    token = cookies.get(TOKEN_COOKIE)
    check(f"{title}: cookie сессии поставлена", token is not None, list(cookies))
    if token:
        days = (token["expires"] - time.time()) / 86400 if token["expires"] > 0 else 0
        check(f"{title}: сессия запомнена надолго (>= 20 дней)", days >= 20, f"{days:.1f} дн.")

    # 2. Навигация смены видна на телефоне.
    nav = page.locator(".top__nav a").first
    check(f"{title}: ссылки разделов видны на телефоне", nav.is_visible(),
          "навигация скрыта — на страницах смены нижней панели нет")
    check(f"{title}: кнопка выхода видна", page.locator("#logout-button").is_visible())
    check(f"{title}: видно, кто на смене", page.locator(".top__who").count() == 1)

    # 3. Возврат с вложенной страницы.
    page.click('.top__nav a[href="/scan"]')
    page.wait_for_url("**/scan", timeout=20_000)
    back = page.locator(".back-link").first
    check(f"{title}: на сканере есть возврат", back.is_visible())
    back.click()
    page.wait_for_url("**/staff", timeout=20_000)
    check(f"{title}: возврат ведёт в панель смены", "/staff" in page.url, page.url)

    # 4. Выход из шапки закрывает панель.
    page.click("#logout-button")
    page.wait_for_url("**/login**", timeout=20_000)
    check(f"{title}: выход вернул на страницу входа", "/login" in page.url, page.url)

    page.goto(f"{BASE}/staff", wait_until="domcontentloaded")
    check(f"{title}: после выхода панель закрыта", "/login" in page.url, page.url)

    # 5. Без галочки сессия короче.
    login(page, remember=False)
    short = {cookie["name"]: cookie for cookie in context.cookies()}.get(TOKEN_COOKIE)
    if short:
        hours = (short["expires"] - time.time()) / 3600 if short["expires"] > 0 else 0
        check(f"{title}: без галочки сессия короче суток", 0 < hours <= 24, f"{hours:.1f} ч")

    check(f"{title}: без ошибок в консоли", not errors, errors[:3])
    browser.close()


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:  # pragma: no cover
        print("нужен playwright: pip install playwright && playwright install chromium webkit")
        return 2

    with sync_playwright() as p:
        run_engine(p.chromium, "chromium (Chrome/Edge)")
        run_engine(p.webkit, "webkit (движок Safari)")

    print(f"\nИТОГО проверок: {checks}, провалов: {len(failures)}")
    for item in failures:
        print("  ПРОВАЛ:", item)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
