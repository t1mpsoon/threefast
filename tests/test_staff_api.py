"""Тесты API персонала и администратора (Ф-6, Ф-7, Ф-8, права доступа)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import ADMIN_PASSWORD, STAFF_PASSWORD, next_local_slot, order_payload


def _create_order(client: TestClient, establishment, menu, key: str = "staff-test-key-01") -> dict:
    response = client.post(
        "/api/orders",
        json=order_payload(establishment.id, [(menu[0].id, 1)], next_local_slot(), key=key),
    )
    assert response.status_code == 201, response.text
    return response.json()


# ── Авторизация ─────────────────────────────────────────────────────────────
def test_unauthorized_staff_access(client: TestClient) -> None:
    """Negative: запрос без токена -> 401."""
    response = client.patch("/api/staff/orders/1/status", json={"new_status": "ready", "version": 1})
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


def test_login_with_wrong_password(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"username": "staff", "password": "wrong-pass"})
    assert response.status_code == 401


def test_login_with_unknown_user(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"username": "nobody", "password": "whatever"})
    assert response.status_code == 401


def test_login_returns_token_and_role(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "admin"
    assert body["role_title"] == "Администратор"
    assert body["access_token"]
    assert body["expires_in_minutes"] > 0


def test_invalid_token_rejected(client: TestClient) -> None:
    response = client.get("/api/staff/orders", headers={"Authorization": "Bearer not-a-token"})
    assert response.status_code == 401


def test_staff_cannot_access_admin_analytics(client: TestClient, staff_headers) -> None:
    """Роли: сотрудник не видит аналитику (403)."""
    response = client.get("/api/staff/analytics", headers=staff_headers)
    assert response.status_code == 403


def test_staff_cannot_change_settings(client: TestClient, staff_headers) -> None:
    response = client.put(
        "/api/staff/settings",
        headers=staff_headers,
        json={
            "slot_duration_minutes": 10,
            "slot_capacity": 9,
            "opens_at": "09:00",
            "closes_at": "18:00",
        },
    )
    assert response.status_code == 403


def test_me_endpoint(client: TestClient, staff_headers) -> None:
    response = client.get("/api/auth/me", headers=staff_headers)
    assert response.status_code == 200
    assert response.json()["username"] == "staff"


def test_logout_clears_cookie(client: TestClient) -> None:
    client.post("/api/auth/login", json={"username": "staff", "password": STAFF_PASSWORD})
    response = client.post("/api/auth/logout")
    assert response.status_code == 204


# ── Ф-6: очередь и переходы статусов ────────────────────────────────────────
def test_queue_returns_orders_sorted_by_slot(client: TestClient, staff_headers,
                                             establishment, menu) -> None:
    first = _create_order(client, establishment, menu, key="queue-key-0001")
    second_payload = order_payload(
        establishment.id, [(menu[1].id, 1)], next_local_slot(minutes_ahead=90), key="queue-key-0002"
    )
    assert client.post("/api/orders", json=second_payload).status_code == 201

    response = client.get("/api/staff/orders", headers=staff_headers)
    assert response.status_code == 200
    queue = response.json()
    times = [order["slot_datetime"] for order in queue]
    assert times == sorted(times)
    assert any(order["order_code"] == first["order_code"] for order in queue)
    assert {order["status"] for order in queue} <= {"confirmed", "in_progress", "ready"}


def test_staff_status_transition_flow(client: TestClient, staff_headers,
                                      establishment, menu) -> None:
    """confirmed -> in_progress -> ready -> picked_up."""
    created = _create_order(client, establishment, menu, key="flow-key-0001")
    queue = client.get("/api/staff/orders", headers=staff_headers).json()
    order = next(item for item in queue if item["order_code"] == created["order_code"])
    assert order["allowed_transitions"]
    version = order["version"]

    for target in ("in_progress", "ready", "picked_up"):
        response = client.patch(
            f"/api/staff/orders/{order['id']}/status",
            headers=staff_headers,
            json={"new_status": target, "version": version},
        )
        assert response.status_code == 200, response.text
        version = response.json()["version"]
        assert response.json()["status"] == target


def test_invalid_transition_confirmed_to_picked_up(client: TestClient, staff_headers,
                                                   establishment, menu) -> None:
    created = _create_order(client, establishment, menu, key="bad-transition-1")
    queue = client.get("/api/staff/orders", headers=staff_headers).json()
    order = next(item for item in queue if item["order_code"] == created["order_code"])

    response = client.patch(
        f"/api/staff/orders/{order['id']}/status",
        headers=staff_headers,
        json={"new_status": "picked_up", "version": order["version"]},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_status_transition"


def test_concurrent_status_update_conflict(client: TestClient, staff_headers,
                                           establishment, menu) -> None:
    """Optimistic locking: второй запрос с устаревшей версией -> 409."""
    created = _create_order(client, establishment, menu, key="conflict-key-001")
    queue = client.get("/api/staff/orders", headers=staff_headers).json()
    order = next(item for item in queue if item["order_code"] == created["order_code"])
    stale_version = order["version"]

    first = client.patch(
        f"/api/staff/orders/{order['id']}/status",
        headers=staff_headers,
        json={"new_status": "in_progress", "version": stale_version},
    )
    assert first.status_code == 200

    second = client.patch(
        f"/api/staff/orders/{order['id']}/status",
        headers=staff_headers,
        json={"new_status": "ready", "version": stale_version},
    )
    assert second.status_code == 409, second.text
    assert second.json()["code"] == "version_conflict"


def test_status_change_for_foreign_order_is_404(client: TestClient, staff_headers) -> None:
    response = client.patch(
        "/api/staff/orders/999999/status",
        headers=staff_headers,
        json={"new_status": "in_progress", "version": 1},
    )
    assert response.status_code == 404


# ── Ф-7: управление меню ────────────────────────────────────────────────────
def test_admin_can_create_and_update_menu_item(client: TestClient, admin_headers,
                                               establishment) -> None:
    payload = {
        "name": "Манты",
        "category": "Основные блюда",
        "price": "1500.00",
        "prep_time_minutes": 20,
        "is_active": True,
    }
    created = client.post("/api/staff/menu", headers=admin_headers, json=payload)
    assert created.status_code == 201, created.text
    item_id = created.json()["id"]

    updated = client.put(
        f"/api/staff/menu/{item_id}",
        headers=admin_headers,
        json={**payload, "price": "1600.00", "is_active": False},
    )
    assert updated.status_code == 200
    assert updated.json()["price"] == 1600.0
    assert updated.json()["is_active"] is False


def test_menu_validation_rejects_bad_price_and_name(client: TestClient, admin_headers) -> None:
    bad_price = client.post(
        "/api/staff/menu",
        headers=admin_headers,
        json={"name": "Суп", "price": "0", "prep_time_minutes": 5},
    )
    assert bad_price.status_code == 422

    short_name = client.post(
        "/api/staff/menu",
        headers=admin_headers,
        json={"name": "С", "price": "100", "prep_time_minutes": 5},
    )
    assert short_name.status_code == 422


def test_delete_item_used_in_orders_deactivates_it(client: TestClient, admin_headers,
                                                   establishment, menu) -> None:
    """Edge case Ф-7: блюдо из заказов не удаляется физически, а скрывается."""
    _create_order(client, establishment, menu, key="menu-delete-key1")
    item_id = menu[0].id

    response = client.delete(f"/api/staff/menu/{item_id}", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["deleted"] is False
    assert response.json()["is_active"] is False

    # История заказа сохранена, блюдо больше не продаётся.
    menu_response = client.get(f"/api/establishments/{establishment.id}/menu")
    assert all(item["id"] != item_id for item in menu_response.json()["items"])


def test_delete_unused_item_removes_it(client: TestClient, admin_headers, establishment) -> None:
    created = client.post(
        "/api/staff/menu",
        headers=admin_headers,
        json={"name": "Временное блюдо", "price": "100.00", "prep_time_minutes": 3},
    )
    item_id = created.json()["id"]

    response = client.delete(f"/api/staff/menu/{item_id}", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["deleted"] is True


def test_toggle_menu_item_visibility(client: TestClient, admin_headers, menu) -> None:
    item_id = menu[0].id
    hidden = client.patch(f"/api/staff/menu/{item_id}/active?is_active=false", headers=admin_headers)
    assert hidden.status_code == 200
    assert hidden.json()["is_active"] is False

    shown = client.patch(f"/api/staff/menu/{item_id}/active?is_active=true", headers=admin_headers)
    assert shown.status_code == 200
    assert shown.json()["is_active"] is True


def test_staff_menu_list_includes_hidden_items(client: TestClient, staff_headers, menu) -> None:
    response = client.get("/api/staff/menu", headers=staff_headers)
    assert response.status_code == 200
    assert len(response.json()) == len(menu)


# ── Ф-8: настройки слотов ───────────────────────────────────────────────────
def test_admin_can_update_slot_settings(client: TestClient, admin_headers) -> None:
    response = client.put(
        "/api/staff/settings",
        headers=admin_headers,
        json={
            "slot_duration_minutes": 10,
            "slot_capacity": 5,
            "opens_at": "08:00",
            "closes_at": "20:00",
            "baseline_orders_per_day": 40,
            "baseline_wait_minutes": 20,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["slot_duration_minutes"] == 10
    assert body["slot_capacity"] == 5
    assert body["capacity_per_hour"] == 30  # (60/10) * 5

    slots = client.get("/api/establishments/1/slots").json()["slots"]
    assert slots[0]["slot_datetime"][11:16] == "08:00"


def test_settings_validation_rejects_zero_capacity(client: TestClient, admin_headers) -> None:
    response = client.put(
        "/api/staff/settings",
        headers=admin_headers,
        json={
            "slot_duration_minutes": 5,
            "slot_capacity": 0,
            "opens_at": "09:00",
            "closes_at": "18:00",
        },
    )
    assert response.status_code == 422


def test_capacity_change_keeps_existing_bookings(client: TestClient, admin_headers,
                                                 establishment, menu) -> None:
    """Edge case Ф-8: новые значения не отменяют уже сделанные брони."""
    created = _create_order(client, establishment, menu, key="capacity-key-01")
    code = created["order_code"]

    client.put(
        "/api/staff/settings",
        headers=admin_headers,
        json={
            "slot_duration_minutes": 5,
            "slot_capacity": 7,
            "opens_at": "00:00",
            "closes_at": "23:55",
            "baseline_orders_per_day": 35,
            "baseline_wait_minutes": 20,
        },
    )

    status_response = client.get(f"/api/orders/{code}/status")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "confirmed"


def test_create_staff_user_requires_admin(client: TestClient, staff_headers, admin_headers) -> None:
    payload = {"username": "cook", "password": "cook-pass-123", "role": "staff"}

    forbidden = client.post("/api/auth/users", headers=staff_headers, json=payload)
    assert forbidden.status_code == 403

    created = client.post("/api/auth/users", headers=admin_headers, json=payload)
    assert created.status_code == 201, created.text

    duplicate = client.post("/api/auth/users", headers=admin_headers, json=payload)
    assert duplicate.status_code == 400

# ── Пароль кухни: администратор точки решает сам ────────────────────────────
def test_kitchen_password_reset_by_admin(client: TestClient, admin_headers,
                                         staff_headers, users) -> None:
    """Администратор заведения выдаёт новый пароль кухне, и он работает."""
    response = client.post("/api/staff/kitchen-password", headers=admin_headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["username"] == users["staff"].username
    assert len(payload["password"]) >= 8
    assert "один раз" in payload["message"]

    # Новый пароль действительно открывает смену кухни.
    login = client.post("/api/auth/login", json={
        "username": payload["username"], "password": payload["password"]
    })
    assert login.status_code == 200, login.text
    assert login.json()["role"] == "staff"

    # Старый пароль больше не действует.
    old = client.post("/api/auth/login", json={
        "username": payload["username"], "password": STAFF_PASSWORD
    })
    assert old.status_code == 401


def test_kitchen_password_is_forbidden_for_staff(client: TestClient, staff_headers) -> None:
    """Кухня не может менять себе пароль: ручка только для администратора."""
    response = client.post("/api/staff/kitchen-password", headers=staff_headers)
    assert response.status_code == 403, response.text


def test_kitchen_password_does_not_touch_admin(client: TestClient, admin_headers,
                                               users) -> None:
    """Пароль администратора заведения при сбросе не меняется."""
    before = users["admin"].password_hash
    response = client.post("/api/staff/kitchen-password", headers=admin_headers)
    assert response.status_code == 200

    login = client.post("/api/auth/login", json={
        "username": users["admin"].username, "password": ADMIN_PASSWORD
    })
    assert login.status_code == 200, "пароль администратора сломался"
    assert users["admin"].password_hash == before


# ── Профиль заведения: только своё и только разрешённые поля ────────────────
def test_admin_updates_own_profile(client: TestClient, admin_headers) -> None:
    """Администратор правит адрес, кухню, фото и часы своего заведения."""
    response = client.put("/api/staff/profile", headers=admin_headers, json={
        "address": "  ул. Новая, 42 ",
        "cuisine": "Азиатская",
        "photo": "/static/img/places/green.jpg",
        "opens_at": "08:30",
        "closes_at": "22:30",
    })
    assert response.status_code == 200, response.text
    profile = response.json()

    assert profile["address"] == "ул. Новая, 42", "пробелы должны обрезаться"
    assert profile["cuisine"] == "Азиатская"
    assert profile["opens_at"] == "08:30"
    assert profile["closes_at"] == "22:30"

    # Чтение отдаёт то же самое.
    again = client.get("/api/staff/profile", headers=admin_headers)
    assert again.status_code == 200
    assert again.json()["address"] == "ул. Новая, 42"


def test_profile_ignores_slot_settings(client: TestClient, admin_headers) -> None:
    """Вместимость и шаг слотов через профиль не меняются.

    Для них есть отдельная ручка: у вместимости другая логика — она
    применяется только к будущим слотам.
    """
    settings_before = client.get("/api/staff/settings", headers=admin_headers).json()

    response = client.put("/api/staff/profile", headers=admin_headers, json={
        "address": "ул. Проверка, 1",
        # Эти поля ручка не принимает — они должны быть проигнорированы.
        "slot_capacity": 99,
        "slot_duration_minutes": 60,
    })
    assert response.status_code == 200, response.text

    settings_after = client.get("/api/staff/settings", headers=admin_headers).json()
    assert settings_after["slot_capacity"] == settings_before["slot_capacity"]
    assert settings_after["slot_duration_minutes"] == settings_before["slot_duration_minutes"]


def test_profile_is_forbidden_for_staff(client: TestClient, staff_headers) -> None:
    """Кухня профиль не читает и не меняет."""
    assert client.get("/api/staff/profile", headers=staff_headers).status_code == 403
    assert client.put("/api/staff/profile", headers=staff_headers,
                      json={"address": "ул. Чужая, 1"}).status_code == 403


def test_profile_rejects_half_of_the_hours(client: TestClient, admin_headers) -> None:
    """Часы работы меняются парой: одно поле без другого — ошибка."""
    response = client.put("/api/staff/profile", headers=admin_headers,
                          json={"opens_at": "10:00"})
    assert response.status_code == 400, response.text


def test_profile_changes_only_own_establishment(client: TestClient, admin_headers,
                                                establishment, db) -> None:
    """Профиль правит заведение администратора, а не первое попавшееся."""
    from app.models.establishment import Establishment

    other = Establishment(
        name="Соседняя точка",
        address="ул. Другая, 9",
        opens_at=establishment.opens_at,
        closes_at=establishment.closes_at,
        slot_duration_minutes=establishment.slot_duration_minutes,
        slot_capacity=establishment.slot_capacity,
    )
    db.add(other)
    db.commit()

    response = client.put("/api/staff/profile", headers=admin_headers,
                          json={"address": "ул. Своя, 7"})
    assert response.status_code == 200
    assert response.json()["establishment_id"] == establishment.id

    db.refresh(other)
    assert other.address == "ул. Другая, 9", "чужое заведение изменилось"
