"""Доступ к данным заведений и меню. Без бизнес-логики (раздел 3.1 ТЗ)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.establishment import Establishment
from app.models.menu_item import MenuItem


class EstablishmentRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, establishment_id: int) -> Establishment | None:
        return self.db.get(Establishment, establishment_id)

    def get_first(self) -> Establishment | None:
        return self.db.scalars(select(Establishment).order_by(Establishment.id)).first()

    def list_all(self) -> list[Establishment]:
        return list(self.db.scalars(select(Establishment).order_by(Establishment.id)))

    def update_settings(
        self,
        establishment: Establishment,
        *,
        slot_duration_minutes: int | None = None,
        slot_capacity: int | None = None,
        opens_at=None,
        closes_at=None,
        baseline_orders_per_day: int | None = None,
        baseline_wait_minutes=None,
    ) -> Establishment:
        if slot_duration_minutes is not None:
            establishment.slot_duration_minutes = slot_duration_minutes
        if slot_capacity is not None:
            establishment.slot_capacity = slot_capacity
        if opens_at is not None:
            establishment.opens_at = opens_at
        if closes_at is not None:
            establishment.closes_at = closes_at
        if baseline_orders_per_day is not None:
            establishment.baseline_orders_per_day = baseline_orders_per_day
        if baseline_wait_minutes is not None:
            establishment.baseline_wait_minutes = baseline_wait_minutes
        self.db.flush()
        return establishment


class MenuRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_for_establishment(
        self, establishment_id: int, *, only_active: bool = False
    ) -> list[MenuItem]:
        stmt = select(MenuItem).where(MenuItem.establishment_id == establishment_id)
        if only_active:
            stmt = stmt.where(MenuItem.is_active.is_(True))
        stmt = stmt.order_by(MenuItem.category, MenuItem.id)
        return list(self.db.scalars(stmt))

    def get(self, menu_item_id: int) -> MenuItem | None:
        return self.db.get(MenuItem, menu_item_id)

    def get_many(self, identifiers: list[int]) -> list[MenuItem]:
        if not identifiers:
            return []
        stmt = select(MenuItem).where(MenuItem.id.in_(identifiers))
        return list(self.db.scalars(stmt))

    def count_ordered(self, menu_item_id: int) -> int:
        """Сколько раз блюдо встречается в заказах — решает, можно ли удалять физически."""
        from app.models.order_item import OrderItem

        stmt = select(func.count(OrderItem.id)).where(OrderItem.menu_item_id == menu_item_id)
        return int(self.db.scalar(stmt) or 0)

    # ── Витрина главного экрана ────────────────────────────────────────────
    def count_active(self) -> int:
        stmt = select(func.count(MenuItem.id)).where(MenuItem.is_active.is_(True))
        return int(self.db.scalar(stmt) or 0)

    def average_prep_time(self) -> int:
        stmt = select(func.avg(MenuItem.prep_time_minutes)).where(MenuItem.is_active.is_(True))
        value = self.db.scalar(stmt)
        return int(round(float(value))) if value is not None else 0

    def list_active_with_place(self) -> list[MenuItem]:
        """Активные блюда вместе с заведением — для витрины популярного."""
        from sqlalchemy.orm import joinedload

        stmt = (
            select(MenuItem)
            .options(joinedload(MenuItem.establishment))
            .where(MenuItem.is_active.is_(True))
            .order_by(MenuItem.name)
        )
        return list(self.db.scalars(stmt).unique())

    def create(self, item: MenuItem) -> MenuItem:
        self.db.add(item)
        self.db.flush()
        return item

    def delete(self, item: MenuItem) -> None:
        self.db.delete(item)
        self.db.flush()
