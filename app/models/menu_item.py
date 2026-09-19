"""Позиция меню (таблица menu_items, раздел 2.7 ТЗ)."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:  # pragma: no cover
    from app.models.establishment import Establishment


class MenuItem(Base):
    """Блюдо. Физически не удаляется, если участвовало в заказах — только is_active=False (Ф-7)."""

    __tablename__ = "menu_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    establishment_id: Mapped[int] = mapped_column(
        ForeignKey("establishments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Короткое описание и фото — главный визуальный якорь карточки блюда.
    description: Mapped[str | None] = mapped_column(String(160), nullable=True)
    photo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    prep_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    establishment: Mapped["Establishment"] = relationship(back_populates="menu_items")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MenuItem id={self.id} name={self.name!r} price={self.price}>"
