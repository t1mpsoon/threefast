"""Проверка экрана отменённого заказа в настоящих браузерах.

Два пути, как заказ отменяется в жизни:
  1. гость нажимает «Отменить заказ» и подтверждает — экран сменяется на
     «отменено» с крестиком;
  2. заказ отменяет кухня («Гость не придёт») — открытая страница гостя
     обязана переключиться на тот же экран сама, без перезагрузки руками.

Запуск: python -m tools.check_cancel_browser [базовый_URL] [логин] [пароль]
Требует playwright и запущенный сервер приложения.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
USERNAME = sys.argv[2] if len(sys.argv) > 2 else "staff"
PASSWORD = sys.argv[3] if len(sys.argv) > 3 else "staff-pass-123"
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


def create_order(client: httpx.Client) -> dict:
    menu = client.get("/api/establishments/1/menu").json()["items"]
    tomorrow = (datetime.now() + timedelta(days=1)).date().isoformat()
    slots = client.get(f"/api/establishments/1/slots?date={tomorrow}").json()["slots"]
    free = [slot for slot in slots if slot["available"]]
    if not free:
        raise RuntimeError("нет свободных слотов — проверку не запустить")
    response = client.post("/api/orders", json={
        "establishment_id": 1,
        "slot_datetime": free[0]["slot_datetime"],
        "guest_name": "Проверка Отмены",
        "guest_phone": "8 701 222 33 44",
        "items": [{"menu_item_id": menu[0]["id"], "quantity": 1}],
        "payment_method": "cash_on_pickup",
        "table_number": 3,
        "idempotency_key": f"cancel-check-{int(time.time() * 1000)}",
    })
    if response.status_code != 201:
        raise RuntimeError(f"заказ не создан: {response.status_code} {response.text[:200]}")
    return response.json()


def run_engine(engine, title: str, client: httpx.Client, headers: dict) -> None:
    print(f"\n── {title} ──")
    browser = engine.launch()
    page = browser.new_context(viewport=PHONE).new_page()
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on(
        "console",
        lambda msg: errors.append(msg.text) if msg.type == "error" and "vibrate" not in msg.text else None,
    )

    # ── 1. Гость отменяет сам ──────────────────────────────────────────────
    order = create_order(client)
    page.goto(f"{BASE}/order?code={order['order_code']}&fresh=1", wait_until="domcontentloaded")
    page.wait_for_selector(".check-path", timeout=15_000)
    check(f"{title}: свежий заказ показан с галочкой", page.locator(".check-path").count() == 1)

    page.click("#cancel-button")
    page.wait_for_selector(".dlg__actions button", timeout=10_000)
    page.click('.dlg__actions button:has-text("Да, отменить")')
    page.wait_for_selector(".cross-path", timeout=25_000)

    check(f"{title}: после отмены появился крестик", page.locator(".cross-path").count() == 1)
    headline = page.locator('[data-role="headline"]').inner_text()
    check(f"{title}: в заголовке сказано, что заказ отменён",
          "отменён" in headline, headline)
    check(f"{title}: крестик в красном круге", page.locator(".success__mark--lost").count() == 1)
    check(f"{title}: QR отменённого заказа убран", page.locator(".order-qr").count() == 0)
    check(f"{title}: шкалы прогресса нет", page.locator("[data-progress]").count() == 0)
    check(f"{title}: предлагают заказать заново",
          page.locator('a:has-text("Заказать заново")').count() == 1)
    check(f"{title}: гость видит, что было в заказе",
          "Что было в заказе" in page.locator("#order-card").inner_text())

    # ── 2. Заказ отменяет кухня ────────────────────────────────────────────
    second = create_order(client)
    page.goto(f"{BASE}/order?code={second['order_code']}", wait_until="domcontentloaded")
    page.wait_for_selector("[data-progress]", timeout=15_000)
    check(f"{title}: живой заказ показан карточкой со шкалой",
          page.locator("[data-progress]").count() == 1)

    moved = client.patch(
        f"/api/staff/orders/{second['order_id']}/status",
        headers=headers,
        json={"new_status": "cancelled", "version": 1},
    )
    check(f"{title}: кухня отменила заказ", moved.status_code == 200, moved.text[:200])

    page.wait_for_selector(".cross-path", timeout=25_000)
    check(f"{title}: страница гостя сама переключилась на экран отмены",
          page.locator(".cross-path").count() == 1)

    check(f"{title}: без ошибок в консоли", not errors, errors[:3])
    browser.close()


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:  # pragma: no cover
        print("нужен playwright: pip install playwright && playwright install chromium webkit")
        return 2

    with httpx.Client(base_url=BASE, timeout=60.0) as client:
        login = client.post("/api/auth/login", json={"username": USERNAME, "password": PASSWORD})
        if login.status_code != 200:
            print(f"вход {USERNAME!r} не удался: {login.status_code} {login.text[:200]}")
            return 2
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        with sync_playwright() as p:
            run_engine(p.chromium, "chromium (Chrome/Edge)", client, headers)
            run_engine(p.webkit, "webkit (движок Safari)", client, headers)

    print(f"\nИТОГО проверок: {checks}, провалов: {len(failures)}")
    for item in failures:
        print("  ПРОВАЛ:", item)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
