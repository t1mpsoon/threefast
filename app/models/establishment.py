"""Заведение общественного питания (таблица establishments, раздел 2.7 ТЗ)."""

from __future__ import annotations

from datetime import datetime, time, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Integer, Numeric, String, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, UTCDateTime

if TYPE_CHECKING:  # pragma: no cover
    from app.models.menu_item import MenuItem
    from app.models.staff_user import StaffUser
    from app.models.time_slot import TimeSlot


class Establishment(Base):
    """Точка общепита: часы работы и параметры расчёта слотов."""

    __tablename__ = "establishments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    opens_at: Mapped[time] = mapped_column(Time, nullable=False)
    closes_at: Mapped[time] = mapped_column(Time, nullable=False)
    slot_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    slot_capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    # Эталон "до внедрения" — вводится администратором, т.к. система не знает
    # истории до себя (Ф-9 ТЗ).
    baseline_orders_per_day: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    baseline_wait_minutes: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, default=Decimal("20.00")
    )

    # Витрина: фото, рейтинг и кухня — то, что видит гость в списке заведений.
    photo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cuisine: Mapped[str | None] = mapped_column(String(50), nullable=True)
    rating: Mapped[Decimal] = mapped_column(
        Numeric(2, 1), nullable=False, default=Decimal("4.8")
    )
    reviews_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    menu_items: Mapped[list["MenuItem"]] = relationship(
        back_populates="establishment", cascade="all, delete-orphan", order_by="MenuItem.id"
    )
    time_slots: Mapped[list["TimeSlot"]] = relationship(
        back_populates="establishment", cascade="all, delete-orphan"
    )
    staff_users: Mapped[list["StaffUser"]] = relationship(
        back_populates="establishment", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Establishment id={self.id} name={self.name!r}>"
