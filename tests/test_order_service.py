"""Unit- и integration-тесты сервиса заказов (правила А-2, Б-2, Б-3, В-1)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.errors import (
    InvalidStatusTransitionError,
    NotFoundError,
    VersionConflictError,
)
from app.models.order import Order, OrderStatus
from app.repositories.order_repository import OrderRepository
from app.repositories.slot_repository import SlotRepository
from app.schemas.order import OrderCreateRequest
from app.services.order_service import OrderService
from tests.conftest import next_local_slot, order_payload


# ── Правило В-1: расчёт суммы ───────────────────────────────────────────────
def test_order_total_calculation() -> None:
    """Сумма = Σ(цена × количество) с округлением до копеек."""
    positions = [(Decimal("1800.00"), 2), (Decimal("350.00"), 3)]
    assert OrderService.calculate_total(positions) == Decimal("4650.00")


def test_order_total_empty_cart_is_zero() -> None:
    assert OrderService.calculate_total([]) == Decimal("0.00")


def test_order_total_rounds_to_kopecks() -> None:
    """Округление до копеек (банковское округление Decimal)."""
    assert OrderService.calculate_total([(Decimal("100.004"), 1)]) == Decimal("100.00")
    assert OrderService.calculate_total([(Decimal("100.006"), 1)]) == Decimal("100.01")


# ── Создание заказа ─────────────────────────────────────────────────────────
def test_create_order_reduces_slot_capacity(db: Session, establishment, menu) -> None:
    """Integration: после заказа booked_count слота увеличивается."""
    service = OrderService(db)
    moment = next_local_slot()
    payload = OrderCreateRequest(**order_payload(establishment.id, [(menu[0].id, 2)], moment))

    created = service.create_order(payload)

    assert created.duplicated is False
    assert created.order.order_code.startswith("EX-")
    assert created.order.status == OrderStatus.CONFIRMED.value
    assert created.order.total_amount == Decimal("3600.00")

    slot = SlotRepository(db).find(establishment.id, moment)
    assert slot is not None
    assert slot.booked_count == 1

    items = created.order.items
    assert len(items) == 1
    assert items[0].item_name_snapshot == "Плов"
    assert items[0].item_price_snapshot == Decimal("1800.00")


def test_second_order_on_full_slot_rejected(db: Session, establishment, menu) -> None:
    """Правило А-2: слот с capacity=1 не принимает второй заказ."""
    establishment.slot_capacity = 1
    db.commit()

    service = OrderService(db)
    moment = next_local_slot()
    first = OrderCreateRequest(
        **order_payload(establishment.id, [(menu[0].id, 1)], moment, key="key-first")
    )
    service.create_order(first)

    second = OrderCreateRequest(
        **order_payload(establishment.id, [(menu[1].id, 1)], moment, key="key-second")
    )
    with pytest.raises(Exception) as error:
        service.create_order(second)
    # Слот заполнен, но заказ не «перескочил» в другой слот: бизнес-ошибка, а не 500.
    assert error.type.__name__ in {"InputError", "SlotUnavailableError"}


def test_idempotency_returns_same_order(db: Session, establishment, menu) -> None:
    """Edge case: повторная отправка формы не создаёт дубль."""
    service = OrderService(db)
    moment = next_local_slot()
    payload = OrderCreateRequest(**order_payload(establishment.id, [(menu[0].id, 1)], moment))

    first = service.create_order(payload)
    second = service.create_order(payload)

    assert second.duplicated is True
    assert second.order.id == first.order.id
    assert second.order.order_code == first.order.order_code
    assert len(OrderRepository(db).list_for_queue(establishment.id, moment.date())) == 1


def test_inactive_item_rejected(db: Session, establishment, menu) -> None:
    """Скрытое блюдо нельзя заказать (правило Ф-2)."""
    hidden = next(item for item in menu if not item.is_active)
    payload = OrderCreateRequest(
        **order_payload(establishment.id, [(hidden.id, 1)], next_local_slot())
    )
    with pytest.raises(Exception) as error:
        OrderService(db).create_order(payload)
    assert "недоступно" in str(error.value)


def test_item_from_other_establishment_rejected(db: Session, establishment, menu) -> None:
    from app.models.establishment import Establishment

    other = Establishment(
        name="Другое кафе",
        opens_at=establishment.opens_at,
        closes_at=establishment.closes_at,
        slot_duration_minutes=5,
        slot_capacity=2,
    )
    db.add(other)
    db.commit()

    payload = OrderCreateRequest(
        **order_payload(other.id, [(menu[0].id, 1)], next_local_slot())
    )
    with pytest.raises(NotFoundError):
        OrderService(db).create_order(payload)


def test_price_snapshot_survives_menu_price_change(db: Session, establishment, menu) -> None:
    """Правило В-1: изменение цены в меню не искажает историю заказов."""
    service = OrderService(db)
    moment = next_local_slot()
    payload = OrderCreateRequest(**order_payload(establishment.id, [(menu[0].id, 1)], moment))
    created = service.create_order(payload)

    menu[0].price = Decimal("9999.00")
    db.commit()

    stored = OrderRepository(db).get(created.order.id)
    assert stored is not None
    assert stored.total_amount == Decimal("1800.00")
    assert stored.items[0].item_price_snapshot == Decimal("1800.00")


# ── Правило Б-2: переходы статусов ─────────────────────────────────────────
def test_invalid_status_transition_rejected(db: Session, establishment, menu) -> None:
    """confirmed -> picked_up запрещён."""
    service = OrderService(db)
    moment = next_local_slot()
    created = service.create_order(
        OrderCreateRequest(**order_payload(establishment.id, [(menu[0].id, 1)], moment))
    )

    with pytest.raises(InvalidStatusTransitionError):
        service.change_status(
            created.order.id,
            OrderStatus.PICKED_UP,
            expected_version=1,
            establishment_id=establishment.id,
        )


def test_valid_status_chain_confirmed_to_picked_up(db: Session, establishment, menu) -> None:
    service = OrderService(db)
    moment = next_local_slot()
    created = service.create_order(
        OrderCreateRequest(**order_payload(establishment.id, [(menu[0].id, 1)], moment))
    )
    order_id = created.order.id
    version = 1

    for target in (OrderStatus.IN_PROGRESS, OrderStatus.READY, OrderStatus.PICKED_UP):
        order = service.change_status(
            order_id,
            target,
            expected_version=version,
            establishment_id=establishment.id,
        )
        version = order.version
        assert order.status == target.value

    assert order.ready_at is not None
    assert order.picked_up_at is not None


def test_stale_version_conflict(db: Session, establishment, menu) -> None:
    """Optimistic locking: устаревшая версия -> конфликт."""
    service = OrderService(db)
    moment = next_local_slot()
    created = service.create_order(
        OrderCreateRequest(**order_payload(establishment.id, [(menu[0].id, 1)], moment))
    )
    service.change_status(
        created.order.id,
        OrderStatus.IN_PROGRESS,
        expected_version=1,
        establishment_id=establishment.id,
    )

    with pytest.raises(VersionConflictError):
        service.change_status(
            created.order.id,
            OrderStatus.READY,
            expected_version=1,  # устаревшая версия
            establishment_id=establishment.id,
        )


def test_status_change_other_establishment_not_found(db: Session, establishment, menu) -> None:
    service = OrderService(db)
    created = service.create_order(
        OrderCreateRequest(
            **order_payload(establishment.id, [(menu[0].id, 1)], next_local_slot())
        )
    )
    with pytest.raises(NotFoundError):
        service.change_status(
            created.order.id,
            OrderStatus.IN_PROGRESS,
            expected_version=1,
            establishment_id=establishment.id + 500,
        )


def test_cancel_releases_slot(db: Session, establishment, menu) -> None:
    """Отмена заказа освобождает место в слоте."""
    service = OrderService(db)
    moment = next_local_slot()
    created = service.create_order(
        OrderCreateRequest(**order_payload(establishment.id, [(menu[0].id, 1)], moment))
    )
    assert SlotRepository(db).find(establishment.id, moment).booked_count == 1

    service.change_status(
        created.order.id,
        OrderStatus.CANCELLED,
        expected_version=1,
        establishment_id=establishment.id,
    )
    assert SlotRepository(db).find(establishment.id, moment).booked_count == 0


def test_cancel_after_pickup_rejected(db: Session, establishment, menu) -> None:
    service = OrderService(db)
    created = service.create_order(
        OrderCreateRequest(
            **order_payload(establishment.id, [(menu[0].id, 1)], next_local_slot())
        )
    )
    for target in (OrderStatus.IN_PROGRESS, OrderStatus.READY, OrderStatus.PICKED_UP):
        order = service.change_status(
            created.order.id,
            target,
            expected_version=(
                1 if target is OrderStatus.IN_PROGRESS else
                2 if target is OrderStatus.READY else 3
            ),
            establishment_id=establishment.id,
        )
    with pytest.raises(InvalidStatusTransitionError):
        service.cancel_by_guest(order.order_code)


# ── Правило Б-3: авто-истечение ─────────────────────────────────────────────
def test_order_expires_after_ready_timeout(db: Session, establishment, menu) -> None:
    """Заказ в статусе ready дольше 20 минут -> expired."""
    service = OrderService(db)
    created = service.create_order(
        OrderCreateRequest(
            **order_payload(establishment.id, [(menu[0].id, 1)], next_local_slot())
        )
    )
    order = service.change_status(
        created.order.id, OrderStatus.IN_PROGRESS, expected_version=1,
        establishment_id=establishment.id,
    )
    order = service.change_status(
        created.order.id, OrderStatus.READY, expected_version=order.version,
        establishment_id=establishment.id,
    )

    # Сдвигаем ready_at в прошлое: 25 минут назад при пороге 20 минут.
    ready_at = datetime.now(timezone.utc) - timedelta(minutes=25)
    OrderRepository(db).mark_ready(order.id, ready_at)
    db.commit()

    expired = service.expire_stale_orders()
    assert expired == 1

    db.expire_all()
    refreshed = OrderRepository(db).get(order.id)
    assert refreshed is not None
    assert refreshed.status == OrderStatus.EXPIRED.value


def test_fresh_ready_order_not_expired(db: Session, establishment, menu) -> None:
    service = OrderService(db)
    created = service.create_order(
        OrderCreateRequest(
            **order_payload(establishment.id, [(menu[0].id, 1)], next_local_slot())
        )
    )
    order = service.change_status(
        created.order.id, OrderStatus.IN_PROGRESS, expected_version=1,
        establishment_id=establishment.id,
    )
    service.change_status(
        created.order.id, OrderStatus.READY, expected_version=order.version,
        establishment_id=establishment.id,
    )

    assert service.expire_stale_orders() == 0


def test_order_code_is_not_sequential(db: Session, establishment, menu) -> None:
    """Код заказа случайный — перебрать чужие заказы нельзя (раздел 2.14 ТЗ)."""
    service = OrderService(db)
    codes = set()
    for index in range(5):
        # Каждому заказу — свой слот, иначе сработает ограничение вместимости.
        moment = next_local_slot(minutes_ahead=30 + index * 10)
        created = service.create_order(
            OrderCreateRequest(
                **order_payload(
                    establishment.id, [(menu[0].id, 1)], moment, key=f"idem-key-{index:02d}"
                )
            )
        )
        codes.add(created.order.order_code)
    assert len(codes) == 5
    assert all(len(code) == 7 for code in codes)


def test_get_order_by_unknown_code_raises(db: Session) -> None:
    with pytest.raises(NotFoundError):
        OrderService(db).get_order_by_code("EX-3467")


def test_order_relations_loaded(db: Session, establishment, menu) -> None:
    service = OrderService(db)
    moment = next_local_slot()
    created = service.create_order(
        OrderCreateRequest(**order_payload(establishment.id, [(menu[0].id, 2), (menu[1].id, 3)], moment))
    )
    order: Order = OrderRepository(db).get(created.order.id)
    assert order is not None
    assert order.items_count == 5
    assert order.slot.slot_datetime == moment
    assert order.status_enum is OrderStatus.CONFIRMED
