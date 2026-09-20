"""Экран отменённого заказа: крестик, состав заказа и что делать дальше.

Раньше отмена выглядела как обычная карточка с погасшей шкалой: гость видел
красную плашку «Отменён» и не понимал, всё ли в порядке и что теперь делать.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.order import Order, OrderStatus
from tests.conftest import next_local_slot, order_payload


def _create(client, establishment, menu, key: str = "cancel-key-0001") -> str:
    response = client.post(
        "/api/orders",
        json=order_payload(establishment.id, [(menu[0].id, 1)], next_local_slot(), key=key),
    )
    assert response.status_code == 201, response.text
    return response.json()["order_code"]


def test_cancelled_order_gets_its_own_screen(client, establishment, menu) -> None:
    """После отмены гость видит отдельный экран, а не погасшую карточку."""
    code = _create(client, establishment, menu)
    assert client.post(f"/api/orders/{code}/cancel").status_code == 200

    html = client.get(f"/order?code={code}").text
    assert "cross-path" in html, "нет крестика"
    assert "success__mark--lost" in html, "крестик не в красном круге"
    assert "отменён" in html
    assert "Ничего забирать не нужно" in html, "нет объяснения, что делать"

    assert "Что было в заказе" in html, "гость не видит, что именно отменил"
    assert "Заказать заново" in html, "нет пути оформить заказ снова"
    assert "Проверить другой заказ" in html


def test_lost_screen_has_no_progress_or_qr(client, establishment, menu) -> None:
    """Шкала и QR на отменённом заказе бессмысленны: следить больше не за чем."""
    code = _create(client, establishment, menu, key="cancel-key-0002")
    client.post(f"/api/orders/{code}/cancel")

    html = client.get(f"/order?code={code}").text
    assert "data-progress" not in html
    assert "order-qr" not in html
    assert "Отменить заказ" not in html, "отменять уже нечего"
    # Карточка нужна скрипту: без неё он выходит и статус не обновляется.
    assert 'id="order-card"' in html


def test_cancelled_screen_wins_over_fresh(client, establishment, menu) -> None:
    """Даже с fresh=1 показываем отмену: галочка успеха тут соврала бы."""
    code = _create(client, establishment, menu, key="cancel-key-0003")
    client.post(f"/api/orders/{code}/cancel")

    html = client.get(f"/order?code={code}&fresh=1").text
    assert "cross-path" in html
    assert "check-path" not in html, "галочка успеха на отменённом заказе"


def test_expired_order_uses_the_same_screen(client, db: Session, establishment, menu) -> None:
    """Снятый с выдачи заказ показывается тем же экраном, но со своим текстом."""
    code = _create(client, establishment, menu, key="cancel-key-0004")
    order = db.scalars(select(Order).where(Order.order_code == code)).first()
    assert order is not None
    order.status = OrderStatus.EXPIRED.value
    db.commit()

    html = client.get(f"/order?code={code}").text
    assert "cross-path" in html
    assert "не востребован" in html
    assert "снимается с выдачи" in html, "нет объяснения, почему заказ снят"


def test_active_order_has_no_cross(client, establishment, menu) -> None:
    """У живого заказа крестика нет — он только для отменённых."""
    code = _create(client, establishment, menu, key="cancel-key-0005")
    html = client.get(f"/order?code={code}").text
    assert "cross-path" not in html
    assert "data-progress" in html
    assert "Отменить заказ" in html


def test_success_screen_allows_cancel(client, establishment, menu) -> None:
    """Отменить можно и сразу после оформления: гость мог ошибиться.

    Раньше кнопка была только на карточке заказа, а на экране успеха её
    не было вовсе — отменить свежий заказ было нечем.
    """
    code = _create(client, establishment, menu, key="cancel-key-0006")
    html = client.get(f"/order?code={code}&fresh=1").text
    assert "check-path" in html, "это должен быть экран успеха"
    assert html.count('id="cancel-button"') == 1, "кнопка отмены должна быть ровно одна"
    assert "Отменить заказ" in html
