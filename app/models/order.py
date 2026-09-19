"""Заказ (таблица orders, раздел 2.7 ТЗ) и правила статусов (правило Б-2)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, UTCDateTime

if TYPE_CHECKING:  # pragma: no cover
    from app.models.establishment import Establishment
    from app.models.order_item import OrderItem
    from app.models.time_slot import TimeSlot


class OrderStatus(StrEnum):
    """Статусы заказа. Значения строковые, чтобы читались в БД и логах."""

    CONFIRMED = "confirmed"
    IN_PROGRESS = "in_progress"
    READY = "ready"
    PICKED_UP = "picked_up"
    CANCELLED = "cancelled"
    EXPIRED = "expired"

    @property
    def title(self) -> str:
        return {
            "confirmed": "Принят",
            "in_progress": "Готовится",
            "ready": "Готов к выдаче",
            "picked_up": "Выдан",
            "cancelled": "Отменён",
            "expired": "Не востребован",
        }[self.value]

    @property
    def is_active(self) -> bool:
        """Заказ ещё в работе (виден в очереди персонала)."""
        return self in {OrderStatus.CONFIRMED, OrderStatus.IN_PROGRESS, OrderStatus.READY}

    @property
    def tone(self) -> str:
        """Визуальный тон статуса — один на все экраны.

        guest — заказ принят и ждёт своей минуты;
        active — что-то происходит прямо сейчас;
        done — заказ завершён удачно;
        lost — заказ не доехал до гостя.
        """
        return {
            "confirmed": "guest",
            "in_progress": "active",
            "ready": "active",
            "picked_up": "done",
            "cancelled": "lost",
            "expired": "lost",
        }[self.value]

    @property
    def is_final(self) -> bool:
        """Заказ завершён: гость больше ничего не ждёт."""
        return self in {OrderStatus.PICKED_UP, OrderStatus.CANCELLED, OrderStatus.EXPIRED}

    @property
    def hint(self) -> str:
        """Подсказка для гостя: что происходит и что делать."""
        return {
            "confirmed": "Кухня приняла заказ и начнёт готовить к вашей минуте.",
            "in_progress": "Заказ готовят прямо сейчас.",
            "ready": "Заказ ждёт на полке выдачи. Назовите номер — отдадим сразу.",
            "picked_up": "Заказ выдан. Приятного аппетита.",
            "cancelled": "Заказ отменён. Ничего забирать не нужно.",
            "expired": "Заказ не забрали вовремя, и он снят с выдачи.",
        }[self.value]


class PaymentStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"

    @property
    def title(self) -> str:
        return {
            "pending": "Оплата при получении",
            "paid": "Оплачен",
            "failed": "Ошибка оплаты",
        }[self.value]


class PaymentMethod(StrEnum):
    """Способ оплаты. Платёжный шлюз не подключён — оплата происходит на кассе."""

    CASH_ON_PICKUP = "cash_on_pickup"
    CARD_ON_PICKUP = "card_on_pickup"

    @property
    def title(self) -> str:
        return {
            "cash_on_pickup": "Наличными при получении",
            "card_on_pickup": "Картой при получении",
        }[self.value]


# Разрешённые переходы статусов (правило Б-2 ТЗ).
ALLOWED_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.CONFIRMED: frozenset(
        {OrderStatus.IN_PROGRESS, OrderStatus.CANCELLED, OrderStatus.EXPIRED}
    ),
    OrderStatus.IN_PROGRESS: frozenset(
        {OrderStatus.READY, OrderStatus.CANCELLED, OrderStatus.EXPIRED}
    ),
    OrderStatus.READY: frozenset(
        {OrderStatus.PICKED_UP, OrderStatus.CANCELLED, OrderStatus.EXPIRED}
    ),
    OrderStatus.PICKED_UP: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.EXPIRED: frozenset(),
}

TERMINAL_STATUSES = frozenset(
    {OrderStatus.PICKED_UP, OrderStatus.CANCELLED, OrderStatus.EXPIRED}
)


class Order(Base):
    """Заказ гостя. Гость не имеет аккаунта — идентификация по order_code (раздел 2.14)."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_code: Mapped[str] = mapped_column(String(10), nullable=False, unique=True, index=True)
    establishment_id: Mapped[int] = mapped_column(
        ForeignKey("establishments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    slot_id: Mapped[int] = mapped_column(
        ForeignKey("time_slots.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    guest_name: Mapped[str] = mapped_column(String(100), nullable=False)
    guest_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    # Примечание к заказу: «без лука», «приборы на двоих». Необязательное поле.
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=OrderStatus.CONFIRMED.value, index=True
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    payment_method: Mapped[str] = mapped_column(
        String(30), nullable=False, default=PaymentMethod.CASH_ON_PICKUP.value
    )
    payment_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PaymentStatus.PENDING.value
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    ready_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    picked_up_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    slot: Mapped["TimeSlot"] = relationship()
    establishment: Mapped["Establishment"] = relationship()
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.id"
    )

    # ── Удобные представления ──────────────────────────────────────────────
    @property
    def status_enum(self) -> OrderStatus:
        return OrderStatus(self.status)

    @property
    def slot_datetime(self) -> datetime:
        return self.slot.slot_datetime

    @property
    def items_count(self) -> int:
        return sum(item.quantity for item in self.items)

    @property
    def can_transition_to(self) -> frozenset[OrderStatus]:
        return ALLOWED_TRANSITIONS[self.status_enum]

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Order {self.order_code} status={self.status} total={self.total_amount}>"
