"""Роутеры HTTP-слоя (раздел 2.8 ТЗ)."""

from app.routers import auth, menu, orders, slots, staff

__all__ = ["auth", "menu", "orders", "slots", "staff"]
