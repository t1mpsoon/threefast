"""Доступ к данным заказов. Без бизнес-логики (раздел 3.1 ТЗ)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.order import Order, OrderStatus
from app.models.order_item import OrderItem
from app.models.time_slot import TimeSlot


class OrderRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Чтение ─────────────────────────────────────────────────────────────
    def get(self, order_id: int) -> Order | None:
        stmt = (
            select(Order)
            .options(selectinload(Order.items), joinedload(Order.slot))
            .where(Order.id == order_id)
        )
        return self.db.scalars(stmt).unique().first()

    def get_by_code(self, order_code: str) -> Order | None:
        stmt = (
            select(Order)
            .options(selectinload(Order.items), joinedload(Order.slot))
            .where(Order.order_code == order_code)
        )
        return self.db.scalars(stmt).unique().first()

    def get_by_idempotency_key(self, key: str) -> Order | None:
        stmt = (
            select(Order)
            .options(selectinload(Order.items), joinedload(Order.slot))
            .where(Order.idempotency_key == key)
        )
        return self.db.scalars(stmt).unique().first()

    def code_exists(self, order_code: str) -> bool:
        stmt = select(func.count(Order.id)).where(Order.order_code == order_code)
        return bool(self.db.scalar(stmt))

    def list_for_queue(
        self, establishment_id: int, day: date, *, statuses: tuple[str, ...] | None = None
    ) -> list[Order]:
        """Очередь заказов, отсортированная по времени выдачи (Ф-6).

        Возвращаем все активные заказы заведения, без границы по дате слота:
        вечером заказ оформляют на минуту после полуночи, и он обязан остаться
        в очереди смены, а не пропасть из-за смены суток. Параметр `day`
        сохранён для совместимости вызовов.
        """
        statuses = statuses or (
            OrderStatus.CONFIRMED.value,
            OrderStatus.IN_PROGRESS.value,
            OrderStatus.READY.value,
        )
        stmt = (
            select(Order)
            .join(TimeSlot, Order.slot_id == TimeSlot.id)
            .options(selectinload(Order.items), joinedload(Order.slot))
            .where(
                Order.establishment_id == establishment_id,
                Order.status.in_(statuses),
            )
            .order_by(TimeSlot.slot_datetime, Order.id)
        )
        return list(self.db.scalars(stmt).unique())

    def list_by_ids(self, identifiers: list[int]) -> list[Order]:
        if not identifiers:
            return []
        stmt = (
            select(Order)
            .options(selectinload(Order.items), joinedload(Order.slot))
            .where(Order.id.in_(identifiers))
        )
        return list(self.db.scalars(stmt).unique())

    # ── Запись ─────────────────────────────────────────────────────────────
    def create(self, order: Order, items: list[OrderItem]) -> Order:
        """Создаёт заказ и его позиции в одной транзакции (правило В-1)."""
        order.items = items
        self.db.add(order)
        self.db.flush()
        return order

    def update_status_atomic(
        self, order_id: int, *, new_status: OrderStatus, expected_version: int
    ) -> bool:
        """Optimistic locking: UPDATE ... WHERE version = expected_version.

        Возвращает False, если версия не совпала — значит статус уже изменил
        другой сотрудник (409, раздел 2.11 ТЗ).

        `synchronize_session=False`: bulk-UPDATE не должен молча «растворяться»
        в уже загруженном объекте сессии — иначе последующий refresh вернул бы
        старую версию записи.
        """
        result = self.db.execute(
            Order.__table__.update()
            .where(Order.id == order_id, Order.version == expected_version)
            .values(status=new_status.value, version=Order.version + 1)
            .execution_options(synchronize_session=False)
        )
        self.db.flush()
        return result.rowcount == 1

    def mark_ready(self, order_id: int, moment: datetime) -> None:
        self.db.execute(
            Order.__table__.update().where(Order.id == order_id).values(ready_at=moment)
        )
        self.db.flush()

    def mark_picked_up(self, order_id: int, moment: datetime) -> None:
        self.db.execute(
            Order.__table__.update().where(Order.id == order_id).values(picked_up_at=moment)
        )
        self.db.flush()

    def mark_cancelled(self, order_id: int, moment: datetime) -> None:
        self.db.execute(
            Order.__table__.update().where(Order.id == order_id).values(cancelled_at=moment)
        )
        self.db.flush()

    def clear_ready_at(self, order_id: int) -> None:
        self.db.execute(
            Order.__table__.update().where(Order.id == order_id).values(ready_at=None)
        )
        self.db.flush()

    def count_created_on(self, day: date) -> int:
        """Сколько заказов оформили за день — показатель для главного экрана."""
        start = datetime.combine(day, time.min).replace(tzinfo=timezone.utc)
        end = datetime.combine(day, time.max).replace(tzinfo=timezone.utc)
        stmt = select(func.count(Order.id)).where(
            Order.created_at >= start, Order.created_at <= end
        )
        return int(self.db.scalar(stmt) or 0)
