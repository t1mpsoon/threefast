"""Смоук-тест на временной БД: полный клиентский флоу из 3 шагов + панель персонала.

Запуск: .\\venv\\Scripts\\python.exe smoke_test.py
"""

from __future__ import annotations

# Разные имена, чтобы в демо-очереди не было десятка одинаковых гостей.
GUEST_NAMES = ["Айгерим", "Данияр", "Мадина", "Тимур", "Асель", "Ерасыл",
               "Камила", "Нурлан", "Жанна", "Арман", "Сабина", "Мирас"]

import os
import random
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TEMP_DB = Path(tempfile.gettempdir()) / "express_pickup_smoke.db"
if TEMP_DB.exists():
    TEMP_DB.unlink()

# Все настройки задаются ДО импорта приложения.
os.environ["DATABASE_URL"] = f"sqlite:///{TEMP_DB.as_posix()}"
os.environ["SECRET_KEY"] = "smoke-test-secret-key"
os.environ["ENABLE_SCHEDULER"] = "false"
os.environ["SEED_ADMIN_PASSWORD"] = "admin-pass-123"
os.environ["SEED_STAFF_PASSWORD"] = "staff-pass-123"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, extra: object = "") -> None:
    mark = "OK  " if condition else "FAIL"
    print(f"[{mark}] {label} {extra if not condition else ''}")
    if not condition:
        failures.append(label)


def main() -> int:
    with TestClient(app) as client:
        # 0. Служебные эндпоинты
        check("GET /health -> 200", client.get("/health").status_code == 200)

        # 1. Шаг 1: меню
        menu = client.get("/api/establishments/1/menu")
        check("Шаг 1: GET меню -> 200", menu.status_code == 200, menu.text[:200])
        menu_json = menu.json()
        check("Шаг 1: в меню есть блюда", len(menu_json["items"]) >= 5, menu_json)
        item = menu_json["items"][0]

        # 2. Шаг 2: слоты (сначала сегодня; если заведение уже закрылось — на завтра,
        #    поведение «после закрытия слотов нет» проверяется отдельной проверкой)
        today_response = client.get("/api/establishments/1/slots")
        check("Шаг 2: GET слоты на сегодня -> 200", today_response.status_code == 200,
              today_response.text[:200])
        today_slots = today_response.json()
        print(f"      сегодня доступно слотов: {today_slots['available_count']} "
              f"({today_slots.get('message') or 'слоты есть'})")

        tomorrow = (datetime.now() + timedelta(days=1)).date().isoformat()
        slots = client.get(f"/api/establishments/1/slots?date={tomorrow}")
        check("Шаг 2: GET слоты на завтра -> 200", slots.status_code == 200, slots.text[:200])
        slots_json = slots.json()
        available = [s for s in slots_json["slots"] if s["available"]]
        check("Шаг 2: на завтра есть доступные слоты", len(available) > 0, slots_json.get("message"))

        # Слоты вне рабочих часов не показываются вовсе (edge case раздела 2.15)
        check("Слоты вне рабочих часов отсутствуют",
              all(9 <= int(s["slot_datetime"][11:13]) <= 18 for s in slots_json["slots"]),
              [s["slot_datetime"] for s in slots_json["slots"]][:3])

        # Запрос слотов на прошедшую дату -> 400
        past = (datetime.now() - timedelta(days=1)).date().isoformat()
        past_response = client.get(f"/api/establishments/1/slots?date={past}")
        check("Негатив: слоты на прошлую дату -> 400", past_response.status_code == 400,
              f"{past_response.status_code} {past_response.text[:150]}")

        # 3. Шаг 3: создание заказа
        if available:
            chosen = available[0]["slot_datetime"]
        else:
            chosen = (datetime.now() + timedelta(days=1)).replace(
                hour=12, minute=0, second=0, microsecond=0
            ).isoformat()
        payload = {
            "establishment_id": 1,
            "slot_datetime": chosen,
            "guest_name": random.choice(GUEST_NAMES),
            "guest_phone": "8 701 123 45 67",
            "items": [{"menu_item_id": item["id"], "quantity": 2}],
            "payment_method": "cash_on_pickup",
            "idempotency_key": "smoke-test-key-0001",
        }
        created = client.post("/api/orders", json=payload)
        check("Шаг 3: POST /api/orders -> 201", created.status_code == 201, created.text[:300])
        order = created.json()
        code = order.get("order_code", "")
        check("Шаг 3: выдан код заказа EX-XXXX", len(code) == 7, code)

        # 4. Идемпотентность
        repeat = client.post("/api/orders", json=payload)
        check("Идемпотентность: повтор -> 200 и тот же код",
              repeat.status_code == 200 and repeat.json()["order_code"] == code,
              (repeat.status_code, repeat.text[:200]))

        # 5. Статус по коду
        status_response = client.get(f"/api/orders/{code}/status")
        check("Статус заказа: 200 и confirmed",
              status_response.status_code == 200 and status_response.json()["status"] == "confirmed",
              status_response.text[:200])

        # 6. Валидация телефона
        bad_phone = client.post("/api/orders", json={**payload, "guest_phone": "12345",
                                                     "idempotency_key": "smoke-test-key-0002"})
        check("Негатив: битый телефон -> 422", bad_phone.status_code == 422, bad_phone.text[:200])

        # 7. Неверный код заказа -> 404 (код валидного формата, но такого заказа нет)
        missing = client.get("/api/orders/EX-3467/status")
        check("Негатив: неизвестный код -> 404", missing.status_code == 404, missing.status_code)

        # Код неверного формата -> 400 (доменная проверка кода, а не схема запроса)
        malformed = client.get("/api/orders/123/status")
        check("Негатив: битый код заказа -> 400", malformed.status_code == 400,
              malformed.status_code)

        # 8. Защита панели персонала
        unauthorized = client.patch("/api/staff/orders/1/status",
                                    json={"new_status": "ready", "version": 1})
        check("Безопасность: без токена -> 401", unauthorized.status_code == 401,
              unauthorized.status_code)

        # 9. Вход персонала и смена статуса
        login = client.post("/api/auth/login",
                            json={"username": "staff", "password": "staff-pass-123"})
        check("Вход сотрудника -> 200", login.status_code == 200, login.text[:200])
        token = login.json().get("access_token", "")
        headers = {"Authorization": f"Bearer {token}"}

        queue = client.get(f"/api/staff/orders?date={tomorrow}", headers=headers)
        check("Очередь заказов -> 200 и заказ в ней",
              queue.status_code == 200 and any(o["order_code"] == code for o in queue.json()),
              queue.text[:300])

        version = next(o["version"] for o in queue.json() if o["order_code"] == code)
        order_id = next(o["id"] for o in queue.json() if o["order_code"] == code)

        bad_transition = client.patch(f"/api/staff/orders/{order_id}/status",
                                      json={"new_status": "picked_up", "version": version},
                                      headers=headers)
        check("Правило Б-2: confirmed -> picked_up отклонён (400)",
              bad_transition.status_code == 400, bad_transition.text[:200])

        for target in ("in_progress", "ready", "picked_up"):
            response = client.patch(f"/api/staff/orders/{order_id}/status",
                                    json={"new_status": target, "version": version},
                                    headers=headers)
            check(f"Переход статуса -> {target}", response.status_code == 200, response.text[:200])
            if response.status_code == 200:
                version = response.json()["version"]

        # 10. Конфликт версий (optimistic locking) — на заказе в активном статусе
        second_payload = {**payload, "idempotency_key": "smoke-test-key-0009",
                          "slot_datetime": (available[-1]["slot_datetime"] if available else chosen)}
        second = client.post("/api/orders", json=second_payload)
        check("Второй заказ создан", second.status_code == 201, second.text[:200])
        second_id = second.json().get("order_id")
        second_code = second.json().get("order_code")

        first_update = client.patch(f"/api/staff/orders/{second_id}/status",
                                    json={"new_status": "in_progress", "version": 1},
                                    headers=headers)
        check("Второй заказ -> in_progress (версия 1)", first_update.status_code == 200,
              first_update.text[:200])
        stale_update = client.patch(f"/api/staff/orders/{second_id}/status",
                                    json={"new_status": "ready", "version": 1}, headers=headers)
        check("Optimistic locking: устаревшая версия -> 409", stale_update.status_code == 409,
              f"{stale_update.status_code} {stale_update.text[:150]}")

        # 11. Аналитика админа
        admin_login = client.post("/api/auth/login",
                                  json={"username": "admin", "password": "admin-pass-123"})
        check("Вход администратора -> 200", admin_login.status_code == 200, admin_login.text[:200])
        admin_headers = {"Authorization": f"Bearer {admin_login.json().get('access_token','')}"}
        analytics = client.get("/api/staff/analytics?period=day", headers=admin_headers)
        check("Аналитика -> 200", analytics.status_code == 200, analytics.text[:300])
        if analytics.status_code == 200:
            data = analytics.json()
            print("      метрики:", {k: data[k] for k in
                                     ("orders_count", "picked_up_count", "average_wait_minutes",
                                      "throughput_growth_percent")})

        # 12. Разграничение прав: staff не видит аналитику
        forbidden = client.get("/api/staff/analytics?period=day", headers=headers)
        check("Роли: staff -> аналитика 403", forbidden.status_code == 403, forbidden.status_code)

        # 13. HTML-страницы
        for path in ("/", "/e/1/menu", "/e/1/slots", "/e/1/confirm", "/login",
                     "/staff", "/admin", "/admin/analytics", f"/order?code={code}", "/docs"):
            response = client.get(path, follow_redirects=False)
            check(f"Страница {path} -> 200/3xx", response.status_code in (200, 303, 307),
                  response.status_code)

        # 14. Полный клиентский флоу в браузере (без токена)
        places_page = client.get("/")
        check("Гость видит список заведений без входа",
              places_page.status_code == 200
              and 'id="places"' in places_page.text
              and "place-search" in places_page.text
              and "cuisine-chips" in places_page.text,
              places_page.status_code)

        guest_menu = client.get("/e/1/menu")
        check("Меню заведения открывается без входа",
              guest_menu.status_code == 200
              and "cartbar" in guest_menu.text
              and "time-sheet" in guest_menu.text
              and "checkout-sheet" in guest_menu.text
              and "dish__photo" in guest_menu.text,
              guest_menu.status_code)

        # Старые адреса шагов должны вести на меню, а не отдавать 404
        for legacy in ("/e/1/slots", "/e/1/confirm"):
            response = client.get(legacy, follow_redirects=False)
            check(f"Старый адрес {legacy} ведёт на меню", response.status_code == 307,
                  response.status_code)

        places_api = client.get("/api/establishments")
        check("Витрина отдаёт список заведений", places_api.status_code == 200
              and len(places_api.json()["places"]) >= 1, places_api.text[:200])
        if places_api.status_code == 200:
            first = places_api.json()["places"][0]
            check("В карточке заведения есть фото и состояние кухни",
                  bool(first["photo"]) and first["load"] in {"free", "busy", "packed", "closed"},
                  first)
            check("У карточки есть рейтинг и подпись состояния",
                  first["rating"] > 0 and bool(first["load_label"]), first)

        # 15. Пустая корзина
        empty_cart = client.post("/api/orders", json={**payload, "items": [],
                                                     "idempotency_key": "smoke-test-key-0003"})
        check("Негатив: пустая корзина -> 422", empty_cart.status_code == 422,
              empty_cart.text[:200])

    print("\n" + "=" * 60)
    if failures:
        print(f"ПРОВАЛЕНО проверок: {len(failures)}")
        for label in failures:
            print("  -", label)
        return 1
    print("Все проверки смоук-теста пройдены")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
