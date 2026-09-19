"""Строка заказа со снапшотом цены (таблица order_items, раздел 2.7 ТЗ)."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:  # pragma: no cover
    from app.models.order import Order


class OrderItem(Base):
    """Позиция заказа. Цена и название фиксируются на момент оформления (правило В-1)."""

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    menu_item_id: Mapped[int] = mapped_column(
        ForeignKey("menu_items.id", ondelete="RESTRICT"), nullable=False
    )
    item_name_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    item_price_snapshot: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    order: Mapped["Order"] = relationship(back_populates="items")

    @property
    def line_total(self) -> Decimal:
        return Decimal(self.item_price_snapshot) * self.quantity

    def __repr__(self) -> str:  # pragma: no cover
        return f"<OrderItem {self.item_name_snapshot!r} x{self.quantity}>"
