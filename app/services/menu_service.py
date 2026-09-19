"""Публичные данные меню (Ф-1) и администрирование меню (Ф-7)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.errors import NotFoundError, InputError
from app.logging_utils import get_logger
from app.models.establishment import Establishment
from app.models.menu_item import MenuItem
from app.repositories.menu_repository import EstablishmentRepository, MenuRepository
from app.schemas.menu import MenuItemCreate

logger = get_logger("menu_service")


class MenuService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.menu = MenuRepository(db)
        self.establishments = EstablishmentRepository(db)

    # ── Ф-1: просмотр меню ─────────────────────────────────────────────────
    def get_establishment(self, establishment_id: int) -> Establishment:
        establishment = self.establishments.get(establishment_id)
        if establishment is None:
            raise NotFoundError("Заведение не найдено")
        return establishment

    def list_menu(
        self, establishment_id: int, *, only_active: bool = True
    ) -> tuple[Establishment, list[MenuItem], list[str]]:
        establishment = self.get_establishment(establishment_id)
        items = self.menu.list_for_establishment(establishment_id, only_active=only_active)
        categories: list[str] = []
        for item in items:
            label = item.category or "Прочее"
            if label not in categories:
                categories.append(label)
        return establishment, items, categories

    # ── Ф-7: CRUD в админке ────────────────────────────────────────────────
    def create_item(self, establishment_id: int, payload: MenuItemCreate) -> MenuItem:
        self.get_establishment(establishment_id)
        item = MenuItem(
            establishment_id=establishment_id,
            name=payload.name,
            category=payload.category,
            description=payload.description,
            photo=payload.photo,
            price=payload.price,
            prep_time_minutes=payload.prep_time_minutes,
            is_active=payload.is_active,
        )
        self.menu.create(item)
        self.db.commit()
        self.db.refresh(item)
        logger.info("Добавлено блюдо %r (заведение %s, цена %s)", item.name, establishment_id, item.price)
        return item

    def update_item(self, menu_item_id: int, payload: MenuItemCreate) -> MenuItem:
        item = self.menu.get(menu_item_id)
        if item is None:
            raise NotFoundError("Блюдо не найдено")
        item.name = payload.name
        item.category = payload.category
        item.description = payload.description
        item.photo = payload.photo
        item.price = payload.price
        item.prep_time_minutes = payload.prep_time_minutes
        item.is_active = payload.is_active
        self.db.commit()
        self.db.refresh(item)
        logger.info("Обновлено блюдо id=%s (%r)", item.id, item.name)
        return item

    def set_active(self, menu_item_id: int, is_active: bool) -> MenuItem:
        item = self.menu.get(menu_item_id)
        if item is None:
            raise NotFoundError("Блюдо не найдено")
        item.is_active = is_active
        self.db.commit()
        self.db.refresh(item)
        logger.info("Блюдо id=%s переведено в is_active=%s", item.id, is_active)
        return item

    def delete_item(self, menu_item_id: int) -> tuple[MenuItem, bool]:
        """Удаляет блюдо, если оно не встречается в заказах, иначе деактивирует (Ф-7).

        Возвращает (блюдо, было_ли_удалено_физически).
        """
        item = self.menu.get(menu_item_id)
        if item is None:
            raise NotFoundError("Блюдо не найдено")

        if self.menu.count_ordered(menu_item_id) > 0:
            item.is_active = False
            self.db.commit()
            self.db.refresh(item)
            logger.info(
                "Блюдо id=%s участвует в заказах — деактивировано вместо удаления", menu_item_id
            )
            return item, False

        self.menu.delete(item)
        self.db.commit()
        logger.info("Блюдо id=%s удалено из меню", menu_item_id)
        return item, True
