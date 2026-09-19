"""Слой доступа к данным: только операции с БД, без бизнес-правил (раздел 3.1 ТЗ)."""

from app.repositories.menu_repository import EstablishmentRepository, MenuRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.slot_repository import SlotRepository
from app.repositories.staff_repository import StaffRepository

__all__ = [
    "EstablishmentRepository",
    "MenuRepository",
    "OrderRepository",
    "SlotRepository",
    "StaffRepository",
]
