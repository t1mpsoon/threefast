"""Выбор заведения и столика: плакат для любой точки и столик в заказе.

Проверки появились после того, как плакат открывался только для первого
заведения: администратор сервиса не мог напечатать QR для остальных точек,
а столик существовал лишь как метка в ссылке и до кухни не доходил.
"""

from __future__ import annotations

import re
from datetime import time
from decimal import Decimal
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.models.establishment import Establishment
from tests.conftest import SUPER_PASSWORD, next_local_slot, order_payload

ROOT = Path(__file__).resolve().parent.parent
ROOT_MENU = "Один общий плакат"


def _second_place(db: Session) -> Establishment:
    item = Establishment(
        name="Второе кафе",
        address="г. Алматы, ул. Вторая 2",
        opens_at=time(0, 0),
        closes_at=time(23, 55),
        slot_duration_minutes=5,
        slot_capacity=2,
        baseline_orders_per_day=10,
        baseline_wait_minutes=Decimal("20.00"),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


# ── Плакат ──────────────────────────────────────────────────────────────────

def test_poster_offers_every_place(client, db, establishment) -> None:
    """На странице плаката можно выбрать любое заведение, а не только первое."""
    second = _second_place(db)
    page = client.get(f"/e/{establishment.id}/qr")
    assert page.status_code == 200
    html = page.text
    assert establishment.name in html
    assert second.name in html, "второго заведения нет в списке"
    assert 'name="place"' in html, "нет выбора заведения"
    assert 'name="print"' in html, "нет выбора, что печатать"
    # Первое заведение отмечено выбранным.
    assert f'<option value="{establishment.id}" selected>' in html


def test_poster_for_one_table(client, establishment) -> None:
    """Плакат можно сделать только для выбранного столика."""
    page = client.get(f"/e/{establishment.id}/qr?table=7")
    assert page.status_code == 200
    assert page.text.count("qr-poster__code") == 1, "должен быть ровно один плакат"
    assert "Стол 7" in page.text
    assert "src=table7" in page.text
    assert 'value="table7" selected' in page.text, "выбранный столик не отмечен в списке"


def test_poster_for_whole_hall(client, establishment) -> None:
    """«Все столы» печатает плакат на каждый столик зала."""
    page = client.get(f"/e/{establishment.id}/qr?tables=3")
    assert page.status_code == 200
    assert page.text.count("qr-poster__code") == 3
    for number in (1, 2, 3):
        assert f"src=table{number}" in page.text
    assert 'value="all" selected' in page.text


def test_poster_without_table(client, establishment) -> None:
    """Общий плакат — один и без метки стола."""
    page = client.get(f"/e/{establishment.id}/qr")
    assert page.text.count("qr-poster__code") == 1
    # Подсказка на странице сама упоминает «?src=tableN», поэтому смотрим
    # не на текст, а на саму ссылку, зашитую в QR.
    poster_url = re.search(r'data-qr="([^"]+)"', page.text).group(1)
    assert "src=table" not in poster_url
    assert f'value="one" selected' in page.text
    assert ROOT_MENU in page.text


def test_qr_shortcut_switches_place(client, db, establishment, super_admin) -> None:
    """Администратор сервиса выбирает заведение — раньше открывалось только первое."""
    second = _second_place(db)
    login = client.post("/api/auth/login", json={"username": "superadmin", "password": SUPER_PASSWORD})
    assert login.status_code == 200, login.text

    response = client.get(f"/qr?place={second.id}&print=table4", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"/e/{second.id}/qr?table=4"


def test_qr_shortcut_with_place_is_public(client, establishment) -> None:
    """Форма выбора на плакате не должна уводить гостя на вход.

    Страница плаката открыта всем, и её форма ходит на /qr: если требовать
    там вход, обычный посетитель после выбора заведения попадал на логин.
    """
    response = client.get(f"/qr?place={establishment.id}&print=table2", follow_redirects=False)
    assert response.status_code == 303, response.headers.get("location")
    assert response.headers["location"] == f"/e/{establishment.id}/qr?table=2"


def test_qr_shortcut_keeps_own_place(client, staff_headers, establishment) -> None:
    """Сотрудник точки попадает на плакат своего заведения."""
    response = client.get("/qr", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith(f"/e/{establishment.id}/qr")


def test_qr_shortcut_print_modes(client, super_admin, establishment) -> None:
    """Режимы печати переводятся в понятную ссылку на плакат."""
    client.post("/api/auth/login", json={"username": "superadmin", "password": SUPER_PASSWORD})

    everything = client.get("/qr?print=all&tables=12", follow_redirects=False)
    assert everything.headers["location"] == f"/e/{establishment.id}/qr?tables=12"

    one = client.get("/qr?print=one&tables=12", follow_redirects=False)
    assert one.headers["location"] == f"/e/{establishment.id}/qr"


# ── Столик в заказе ─────────────────────────────────────────────────────────

def _create(client, establishment, menu, table=None, key="table-key-0001"):
    payload = order_payload(establishment.id, [(menu[0].id, 1)], next_local_slot(), key=key)
    if table is not None:
        payload["table_number"] = table
    return client.post("/api/orders", json=payload)


def test_order_keeps_table_number(client, staff_headers, establishment, menu) -> None:
    """Столик из заказа виден и гостю, и кухне."""
    created = _create(client, establishment, menu, table=5)
    assert created.status_code == 201, created.text
    code = created.json()["order_code"]

    status = client.get(f"/api/orders/{code}/status").json()
    assert status["table_number"] == 5

    queue = client.get("/api/staff/orders", headers=staff_headers).json()
    row = next(order for order in queue if order["order_code"] == code)
    assert row["table_number"] == 5, "кухня не увидит, куда нести заказ"


def test_order_without_table_is_takeaway(client, establishment, menu) -> None:
    """Без столика заказ остаётся заказом на вынос."""
    created = _create(client, establishment, menu, key="table-key-0002")
    assert created.status_code == 201, created.text
    status = client.get(f"/api/orders/{created.json()['order_code']}/status").json()
    assert status["table_number"] is None


def test_table_number_is_validated(client, establishment, menu) -> None:
    """Номер столика вне диапазона не принимаем."""
    for bad in (0, 61, -3):
        response = _create(client, establishment, menu, table=bad, key=f"table-key-bad{bad}")
        assert response.status_code == 422, f"столик {bad} принят: {response.text[:150]}"


def test_poster_table_lands_in_checkout(client, establishment) -> None:
    """Метку стола со плаката разбирает оформление и кладёт в заказ."""
    page = client.get(f"/e/{establishment.id}/menu?src=table9")
    assert page.status_code == 200
    assert 'id="guest-table"' in page.text, "на оформлении нет поля для столика"

    checkout = (ROOT / "app" / "static" / "js" / "sheet_checkout.js").read_text(encoding="utf-8")
    assert "table(\\d{1,2})" in checkout, "оформление не разбирает метку стола из ссылки"
    assert "table_number" in checkout, "столик не уходит в заказ"


# ── Догон схемы ─────────────────────────────────────────────────────────────

def test_schema_top_up_adds_missing_column(tmp_path, monkeypatch) -> None:
    """create_all не трогает существующие таблицы — колонку добавляет догон.

    Именно на этом ломался деплой: в модели поле появилось, а в боевой базе
    его не было, и первый же INSERT падал.
    """
    from sqlalchemy import create_engine

    import app.init_db as init_db
    from app.database import Base

    engine = create_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE orders DROP COLUMN table_number"))
    assert "table_number" not in {c["name"] for c in inspect(engine).get_columns("orders")}

    monkeypatch.setattr(init_db, "engine", engine)
    added = init_db.add_missing_columns()

    assert "orders.table_number" in added
    assert "table_number" in {c["name"] for c in inspect(engine).get_columns("orders")}
    # Повторный прогон ничего не ломает и не добавляет.
    assert init_db.add_missing_columns() == []
