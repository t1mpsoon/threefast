"""Временной слот выдачи (таблица time_slots, раздел 2.7 ТЗ)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:  # pragma: no cover
    from app.models.establishment import Establishment


class TimeSlot(Base):
    """Слот = конкретное время выдачи + счётчик занятых мест (правило А-2).

    slot_datetime хранится как «настенное» локальное время заведения (naive):
    слоты — это время на часах кафе, а не момент в UTC.
    """

    __tablename__ = "time_slots"
    __table_args__ = (
        UniqueConstraint("establishment_id", "slot_datetime", name="uq_slot_establishment_datetime"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    establishment_id: Mapped[int] = mapped_column(
        ForeignKey("establishments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    slot_datetime: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    booked_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    establishment: Mapped["Establishment"] = relationship(back_populates="time_slots")

    @property
    def free_places(self) -> int:
        return max(self.capacity - self.booked_count, 0)

    @property
    def is_full(self) -> bool:
        return self.booked_count >= self.capacity

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<TimeSlot est={self.establishment_id} at={self.slot_datetime:%Y-%m-%d %H:%M} "
            f"{self.booked_count}/{self.capacity}>"
        )
