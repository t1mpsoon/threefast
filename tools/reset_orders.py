"""Чистка накопленных демо-заказов: убирает следы прогонов проверок.

Запуск: python -m tools.reset_orders

Удаляются все заказы, их позиции и брони в слотах, после чего очередь смены
пуста и её можно наполнить заново: python -m tools.seed_demo_orders
"""

from __future__ import annotations

import logging
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.disable(logging.CRITICAL)

from sqlalchemy import delete, func, select, update  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.order import Order  # noqa: E402
from app.models.order_item import OrderItem  # noqa: E402
from app.models.time_slot import TimeSlot  # noqa: E402


def main() -> int:
    db = SessionLocal()
    try:
        orders = db.scalar(select(func.count(Order.id))) or 0
        items = db.scalar(select(func.count(OrderItem.id))) or 0

        db.execute(delete(OrderItem))
        db.execute(delete(Order))
        # Освобождаем слоты: брони больше ни за кем не числятся.
        db.execute(update(TimeSlot).values(booked_count=0))
        db.commit()

        left = db.scalar(select(func.count(Order.id))) or 0
        print(f"удалено заказов: {orders}, позиций: {items}")
        print(f"осталось заказов: {left}")
        print("очередь смены пуста — наполните её: python -m tools.seed_demo_orders")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
