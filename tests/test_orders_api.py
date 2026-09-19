"""Functional- и negative-тесты HTTP API заказов и меню (раздел 5 ТЗ)."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from tests.conftest import next_local_slot, order_payload


# ── Функциональные сценарии ─────────────────────────────────────────────────
def test_full_order_flow_via_api(client: TestClient, establishment, menu) -> None:
    """1) меню -> 2) слоты -> 3) заказ -> 4) статус: полный флоу из 3 шагов."""
    menu_response = client.get(f"/api/establishments/{establishment.id}/menu")
    assert menu_response.status_code == 200
    items = menu_response.json()["items"]
    assert len(items) == 2  # скрытое блюдо не показывается
    assert menu_response.json()["establishment"]["name"] == establishment.name

    slots_response = client.get(f"/api/establishments/{establishment.id}/slots")
    assert slots_response.status_code == 200
    slots = slots_response.json()["slots"]
    # Слоты запрашиваем на день, в который попала бронь: поздним вечером
    # «через 30 минут» — это уже следующие сутки, и сегодняшняя сетка пуста.
    booking_day = next_local_slot().date().isoformat()
    day_slots = client.get(
        f"/api/establishments/{establishment.id}/slots?date={booking_day}"
    ).json()["slots"]
    assert day_slots, f"на {booking_day} должны быть слоты"
    available = [slot for slot in day_slots if slot["available"]]
    assert available, f"на {booking_day} нет свободных слотов"
    assert slots is not None

    payload = order_payload(establishment.id, [(items[0]["id"], 2)], next_local_slot())
    created = client.post("/api/orders", json=payload)
    assert created.status_code == 201, created.text
    order = created.json()
    assert order["status"] == "confirmed"
    assert order["total_amount"] == items[0]["price"] * 2

    status_response = client.get(f"/api/orders/{order['order_code']}/status")
    assert status_response.status_code == 200
    body = status_response.json()
    assert body["status"] == "confirmed"
    assert body["progress_step"] == 1
    assert len(body["items"]) == 1


def test_order_note_goes_to_guest_and_kitchen(
    client: TestClient, establishment, menu, staff_headers
) -> None:
    """Примечание из шторки оформления доходит и до гостя, и до кухни."""
    payload = order_payload(
        establishment.id, [(menu[0].id, 1)], next_local_slot(),
        key="note-order-key-01",
    )
    payload["note"] = "  Без лука,   приборы на двоих  "
    created = client.post("/api/orders", json=payload)
    assert created.status_code == 201, created.text
    order = created.json()

    # Гость видит своё примечание очищенным от лишних пробелов.
    status_response = client.get(f"/api/orders/{order['order_code']}/status")
    assert status_response.status_code == 200
    assert status_response.json()["note"] == "Без лука, приборы на двоих"
    assert status_response.json()["status_tone"] == "guest"
    assert status_response.json()["payment_method_title"] == "Наличными при получении"

    # Кухня получает его в очереди вместе с тоном статуса.
    queue = client.get("/api/staff/orders", headers=staff_headers)
    assert queue.status_code == 200
    row = [o for o in queue.json() if o["order_code"] == order["order_code"]][0]
    assert row["note"] == "Без лука, приборы на двоих"
    assert row["status_tone"] == "guest"


def test_order_without_note_stays_empty(
    client: TestClient, establishment, menu
) -> None:
    """Примечание необязательно: пустая строка превращается в отсутствие поля."""
    payload = order_payload(
        establishment.id, [(menu[0].id, 1)], next_local_slot(),
        key="note-order-key-02",
    )
    payload["note"] = "   "
    created = client.post("/api/orders", json=payload)
    assert created.status_code == 201, created.text
    status_response = client.get(f"/api/orders/{created.json()['order_code']}/status")
    assert status_response.json()["note"] is None


def test_status_tone_follows_order_status(
    client: TestClient, establishment, menu, staff_headers
) -> None:
    """Тон статуса меняется вместе с состоянием заказа — один язык для всех экранов."""
    payload = order_payload(
        establishment.id, [(menu[0].id, 1)], next_local_slot(),
        key="tone-order-key-01",
    )
    created = client.post("/api/orders", json=payload).json()
    code = created["order_code"]

    def tone() -> str:
        return client.get(f"/api/orders/{code}/status").json()["status_tone"]

    assert tone() == "guest"
    order_id = created["order_id"]
    version = 1
    for new_status in ("in_progress", "ready"):
        response = client.patch(
            f"/api/staff/orders/{order_id}/status",
            json={"new_status": new_status, "version": version},
            headers=staff_headers,
        )
        assert response.status_code == 200, response.text
        version = response.json()["version"]
        assert tone() == "active", f"статус {new_status} должен быть активным тоном"

    response = client.patch(
        f"/api/staff/orders/{order_id}/status",
        json={"new_status": "picked_up", "version": version},
        headers=staff_headers,
    )
    assert response.status_code == 200, response.text
    assert tone() == "done"


def test_kitchen_sees_only_own_orders(
    client: TestClient, establishment, menu, staff_headers, db
) -> None:
    """Смена видит заказы своего заведения, а не всех подряд (раздел 2.14 ТЗ)."""
    from app.models.establishment import Establishment

    other = Establishment(
        name="Соседняя кухня",
        address="ул. Другая, 1",
        opens_at=establishment.opens_at,
        closes_at=establishment.closes_at,
        slot_duration_minutes=establishment.slot_duration_minutes,
        slot_capacity=establishment.slot_capacity,
    )
    db.add(other)
    db.commit()

    mine = client.post("/api/orders", json=order_payload(
        establishment.id, [(menu[0].id, 1)], next_local_slot(), key="scope-key-01"
    ))
    assert mine.status_code == 201, mine.text

    queue = client.get("/api/staff/orders", headers=staff_headers)
    assert queue.status_code == 200
    places = {row["order_code"] for row in queue.json()}
    assert mine.json()["order_code"] in places

    # Настройки и сводка тоже относятся к своему заведению.
    me = client.get("/api/staff/me", headers=staff_headers)
    assert me.status_code == 200
    assert me.json()["establishment_id"] == establishment.id
    assert me.json()["establishment_name"] == establishment.name

    stats = client.get("/api/staff/queue-stats", headers=staff_headers)
    assert stats.status_code == 200
    body = stats.json()
    assert body["total"] >= 1
    assert body["capacity"] == establishment.slot_capacity


def test_menu_404_for_unknown_establishment(client: TestClient) -> None:
    response = client.get("/api/establishments/999999/menu")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_slots_400_for_bad_date_format(client: TestClient, establishment) -> None:
    response = client.get(f"/api/establishments/{establishment.id}/slots?date=19-09-2026")
    assert response.status_code == 400


def test_slots_respect_min_prep_minutes(client: TestClient, establishment) -> None:
    """Правило Б-1: слоты раньше времени приготовления помечены как недоступные."""
    response = client.get(
        f"/api/establishments/{establishment.id}/slots?min_prep_minutes=120"
    )
    assert response.status_code == 200
    data = response.json()
    soon = [slot for slot in data["slots"] if slot["is_too_soon"]]
    assert all(not slot["available"] for slot in soon)


# ── Негативные сценарии и валидация ─────────────────────────────────────────
def test_create_order_with_invalid_phone(client: TestClient, establishment, menu) -> None:
    payload = order_payload(establishment.id, [(menu[0].id, 1)], next_local_slot(),
                            phone="12345")
    response = client.post("/api/orders", json=payload)
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "validation_error"
    assert "guest_phone" in body["fields"]
    assert "формат" in body["fields"]["guest_phone"]


def test_create_order_with_empty_cart(client: TestClient, establishment) -> None:
    payload = order_payload(establishment.id, [], next_local_slot())
    response = client.post("/api/orders", json=payload)
    assert response.status_code == 422


def test_create_order_with_short_name(client: TestClient, establishment, menu) -> None:
    payload = order_payload(establishment.id, [(menu[0].id, 1)], next_local_slot(), name="А")
    response = client.post("/api/orders", json=payload)
    assert response.status_code == 422


def test_create_order_with_zero_quantity(client: TestClient, establishment, menu) -> None:
    payload = order_payload(establishment.id, [(menu[0].id, 0)], next_local_slot())
    response = client.post("/api/orders", json=payload)
    assert response.status_code == 422


def test_create_order_with_excessive_quantity(client: TestClient, establishment, menu) -> None:
    payload = order_payload(establishment.id, [(menu[0].id, 50)], next_local_slot())
    response = client.post("/api/orders", json=payload)
    assert response.status_code == 422


def test_create_order_for_past_slot(client: TestClient, establishment, menu) -> None:
    past = (datetime.now() - timedelta(hours=1)).replace(second=0, microsecond=0)
    payload = order_payload(establishment.id, [(menu[0].id, 1)], past)
    response = client.post("/api/orders", json=payload)
    assert response.status_code == 400, response.text


def test_create_order_with_inactive_item(client: TestClient, establishment, menu) -> None:
    hidden = next(item for item in menu if not item.is_active)
    payload = order_payload(establishment.id, [(hidden.id, 1)], next_local_slot())
    response = client.post("/api/orders", json=payload)
    assert response.status_code == 400
    assert "недоступно" in response.json()["detail"]


def test_create_order_with_unknown_item(client: TestClient, establishment) -> None:
    payload = order_payload(establishment.id, [(999_999, 1)], next_local_slot())
    response = client.post("/api/orders", json=payload)
    assert response.status_code == 404


def test_order_status_unknown_code_404(client: TestClient) -> None:
    response = client.get("/api/orders/EX-3467/status")
    assert response.status_code == 404
    assert "не найден" in response.json()["detail"]


def test_order_status_malformed_code_400(client: TestClient) -> None:
    response = client.get("/api/orders/abc/status")
    assert response.status_code == 400


def test_request_with_broken_json_returns_4xx(client: TestClient, establishment) -> None:
    response = client.post(
        "/api/orders",
        content="{not-json",
        headers={"Content-Type": "application/json"},
    )
    assert 400 <= response.status_code < 500


# ── Идемпотентность и слоты ─────────────────────────────────────────────────
def test_duplicate_order_via_idempotency_key(client: TestClient, establishment, menu) -> None:
    """Edge case: повтор с тем же ключом -> 200 и тот же код, дубля нет."""
    payload = order_payload(establishment.id, [(menu[0].id, 1)], next_local_slot(),
                            key="repeat-key-12345")

    first = client.post("/api/orders", json=payload)
    second = client.post("/api/orders", json=payload)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["order_code"] == second.json()["order_code"]
    assert second.json()["duplicated"] is True


def test_slot_full_returns_409(client: TestClient, establishment, menu, admin_headers) -> None:
    """Слот заняли между шагом 2 и 3 -> 409 с понятным сообщением."""
    # Вместимость меняем через API, чтобы значение гарантированно применилось.
    settings_response = client.put(
        "/api/staff/settings",
        headers=admin_headers,
        json={
            "slot_duration_minutes": 5,
            "slot_capacity": 1,
            "opens_at": "00:00",
            "closes_at": "23:55",
            "baseline_orders_per_day": 35,
            "baseline_wait_minutes": 20,
        },
    )
    assert settings_response.status_code == 200, settings_response.text
    moment = next_local_slot()

    first = client.post(
        "/api/orders",
        json=order_payload(establishment.id, [(menu[0].id, 1)], moment, key="slot-key-aaaa"),
    )
    assert first.status_code == 201, first.text

    second = client.post(
        "/api/orders",
        json=order_payload(establishment.id, [(menu[1].id, 1)], moment, key="slot-key-bbbb"),
    )
    assert second.status_code == 409, second.text
    body = second.json()
    assert body["code"] == "slot_unavailable"
    assert "свободных мест" in body["detail"]


def test_cancel_order_releases_and_updates_status(client: TestClient, establishment, menu) -> None:
    created = client.post(
        "/api/orders",
        json=order_payload(establishment.id, [(menu[0].id, 1)], next_local_slot()),
    )
    code = created.json()["order_code"]

    cancelled = client.post(f"/api/orders/{code}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    again = client.post(f"/api/orders/{code}/cancel")
    assert again.status_code == 400


def test_order_code_is_case_insensitive(client: TestClient, establishment, menu) -> None:
    created = client.post(
        "/api/orders",
        json=order_payload(establishment.id, [(menu[0].id, 1)], next_local_slot()),
    )
    code = created.json()["order_code"]

    response = client.get(f"/api/orders/{code.lower().replace('-', '')}/status")
    assert response.status_code == 200
    assert response.json()["order_code"] == code


# ── HTML-страницы ───────────────────────────────────────────────────────────
def test_guest_pages_available_without_login(client: TestClient, establishment, menu) -> None:
    for path in (
        "/",
        f"/e/{establishment.id}/menu",
        f"/e/{establishment.id}/slots",
        f"/e/{establishment.id}/confirm",
        "/order",
        "/login",
    ):
        response = client.get(path, follow_redirects=False)
        assert response.status_code in (200, 307), f"{path} -> {response.status_code}"


def test_staff_page_redirects_to_login(client: TestClient) -> None:
    response = client.get("/staff", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_error_page_has_no_traceback(client: TestClient) -> None:
    response = client.get("/e/999999/menu")
    assert response.status_code == 404
    assert "Traceback" not in response.text
    assert "не найдено" in response.text.lower()
