"""Проверка синхронизации кухни и гостя в настоящих браузерах.

Сценарий ровно такой, как в жизни:
  1. гость оформляет заказ и остаётся на экране успеха;
  2. кухня меняет статус у себя;
  3. экран гостя обязан показать новый статус САМ, без перезагрузки;
  4. обратно: новый заказ гостя появляется в очереди смены тоже сам.

Перезагрузку ловим меткой в window: если страница перезагрузилась, метка исчезнет.

Запуск: python -m tools.check_sync_browser [базовый_URL] [логин] [пароль]
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

# Опрос на экране гостя — раз в 5 секунд; даём запас на медленный ответ.
WAIT_MS = 20_000

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


def api_create_order(
    client: httpx.Client, day: str | None = None, min_ahead_minutes: int = 0
) -> tuple[dict | None, str]:
    """Заводит заказ и возвращает (заказ, дата выдачи).

    `min_ahead_minutes` нужен для заказов на сегодня: слот ближе времени
    приготовления блюда сервер отклонит. Если подходящего слота нет,
    возвращается None — вызывающий решает, пропустить проверку или упасть.
    """
    menu = client.get("/api/establishments/1/menu").json()["items"]
    day = day or (datetime.now() + timedelta(days=1)).date().isoformat()
    slots = client.get(f"/api/establishments/1/slots?date={day}").json()["slots"]
    free = [s for s in slots if s["available"]]
    if min_ahead_minutes:
        threshold = datetime.now() + timedelta(minutes=min_ahead_minutes)
        free = [s for s in free if datetime.fromisoformat(s["slot_datetime"]) >= threshold]
    if not free:
        return None, day
    payload = {
        "establishment_id": 1,
        "slot_datetime": free[0]["slot_datetime"],
        "guest_name": "Проверка Связи",
        "guest_phone": "8 701 555 66 77",
        "items": [{"menu_item_id": menu[0]["id"], "quantity": 1}],
        "payment_method": "cash_on_pickup",
        "idempotency_key": f"sync-check-{int(time.time() * 1000)}",
    }
    response = client.post("/api/orders", json=payload)
    if response.status_code != 201:
        raise RuntimeError(f"заказ не создан: {response.status_code} {response.text[:300]}")
    return response.json(), day


def move(client: httpx.Client, headers: dict, order_id: int, version: int, target: str) -> int:
    response = client.patch(
        f"/api/staff/orders/{order_id}/status",
        headers=headers,
        json={"new_status": target, "version": version},
    )
    if response.status_code != 200:
        raise RuntimeError(f"переход в {target} не удался: {response.status_code} {response.text[:200]}")
    return response.json()["version"]


def run_engine(engine, title: str, client: httpx.Client, headers: dict, token: str) -> None:
    print(f"\n── {title} ──")
    order, _ = api_create_order(client)
    if order is None:
        raise RuntimeError("нет свободных слотов на завтра — проверку не запустить")
    code, order_id, version = order["order_code"], order["order_id"], 1

    browser = engine.launch()
    context = browser.new_context(viewport={"width": 420, "height": 900})
    context.add_cookies([{"name": "ep_token", "value": token, "url": BASE}])
    page = context.new_page()
    errors: list[str] = []

    def note(message: str) -> None:
        if "navigator.vibrate" in message:
            return
        errors.append(message)

    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on("console", lambda msg: note(msg.text) if msg.type == "error" else None)

    def state_text() -> str:
        return page.locator('[data-role="state"]').inner_text().strip()

    def headline_text() -> str:
        return page.locator('[data-role="headline"]').inner_text().strip()

    def wait_state(exact: str) -> str:
        """Ждёт точного текста плашки.

        Именно точного: слова «Готовится» и «Выдано» всегда есть в подписях
        шкалы прогресса, и поиск по вхождению срабатывал бы мгновенно.
        """
        deadline = time.time() + WAIT_MS / 1000
        text = ""
        while time.time() < deadline:
            text = state_text()
            if text == exact:
                return text
            page.wait_for_timeout(400)
        return text

    # 1. Гость на экране успеха сразу после оформления.
    page.goto(f"{BASE}/order?code={code}&fresh=1", wait_until="domcontentloaded")
    page.wait_for_selector("#order-card", timeout=10_000)
    check(f"{title}: гость видит «Принят» после оформления", state_text() == "Принят", state_text())
    step = page.locator("[data-progress]").get_attribute("data-step")
    check(f"{title}: шкала стоит на шаге 1, а не забегает вперёд", step == "1", step)

    # Метка переживёт обновление статуса, но не перезагрузку страницы.
    page.evaluate("window.__noReload = true")

    # 2. Кухня начинает готовить.
    version = move(client, headers, order_id, version, "in_progress")
    got = wait_state("Готовится")
    check(f"{title}: статус «Готовится» доехал до гостя сам", got == "Готовится", got)
    head = headline_text()
    check(f"{title}: заголовок экрана обновился", head == f"Заказ {code} готовят", head)
    check(f"{title}: страница не перезагрузилась",
          page.evaluate("Boolean(window.__noReload)") is True)

    # 3. Кухня отмечает готовность.
    version = move(client, headers, order_id, version, "ready")
    got = wait_state("Готов к выдаче")
    check(f"{title}: статус «Готов к выдаче» доехал до гостя", got == "Готов к выдаче", got)
    head = headline_text()
    check(f"{title}: заголовок стал «готов!»", head == f"Заказ {code} готов!", head)
    tone = page.locator("#order-card").get_attribute("data-tone")
    check(f"{title}: тон экрана переключился на «идёт выдача»", tone == "active", tone)

    # 4. Выдача закрывает заказ.
    move(client, headers, order_id, version, "picked_up")
    got = wait_state("Выдан")
    check(f"{title}: статус «Выдан» доехал до гостя", got == "Выдан", got)

    # 5. Обратная сторона: новый заказ появляется в очереди смены сам.
    # Панель кухни показывает сегодняшний день, поэтому заказ берём на сегодня
    # и с запасом по времени приготовления.
    queue = context.new_page()
    queue.goto(f"{BASE}/staff", wait_until="domcontentloaded")
    queue.wait_for_selector("#orders", timeout=10_000)
    queue.wait_for_timeout(1500)
    before = queue.locator(".ticket").count()
    queue.evaluate("window.__noReload = true")

    fresh, _ = api_create_order(client, min_ahead_minutes=15)
    if fresh is None:
        print("[ПРОПУСК] на сегодня не осталось слотов с запасом 15 минут — "
              "очередь кухни сейчас не проверить")
    else:
        found = False
        deadline = time.time() + WAIT_MS / 1000
        while time.time() < deadline:
            if queue.locator(f'.ticket:has-text("{fresh["order_code"]}")').count():
                found = True
                break
            queue.wait_for_timeout(500)
        check(f"{title}: новый заказ гостя появился в очереди кухни", found,
              f"было строк: {before}, ждали {fresh['order_code']}")
        check(f"{title}: очередь обновилась без перезагрузки",
              queue.evaluate("Boolean(window.__noReload)") is True)

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
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        with sync_playwright() as p:
            run_engine(p.chromium, "chromium (Chrome/Edge)", client, headers, token)
            run_engine(p.webkit, "webkit (движок Safari)", client, headers, token)

    print(f"\nИТОГО проверок: {checks}, провалов: {len(failures)}")
    for item in failures:
        print("  ПРОВАЛ:", item)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
