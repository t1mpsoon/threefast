"""Привести демо-данные в порядок: убрать дубли блюд и витрину без фото.

Запуск: python -m tools.clean_demo_data

Идемпотентно: повторный запуск ничего не меняет. Заказы и история не затрагиваются —
блюдо, которое уже заказывали, не удаляется, а скрывается.
"""

from __future__ import annotations

import logging
import sys
from decimal import Decimal

from sqlalchemy import select

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.disable(logging.CRITICAL)

from app.database import SessionLocal  # noqa: E402
from app.init_db import PLACES  # noqa: E402
from app.models.establishment import Establishment  # noqa: E402
from app.models.menu_item import MenuItem  # noqa: E402
from app.models.order_item import OrderItem  # noqa: E402


def main() -> int:
    db = SessionLocal()
    try:
        hidden = 0
        filled = 0

        for spec in PLACES:
            place = db.scalars(
                select(Establishment).where(Establishment.name == spec["name"])
            ).first()
            if place is None:
                continue

            canonical = {row[0] for row in spec["menu"]}
            items = list(db.scalars(
                select(MenuItem).where(MenuItem.establishment_id == place.id)
            ).all())

            for item in items:
                # Дубль того же блюда: канонический вариант остаётся, лишний скрываем.
                if item.name not in canonical:
                    if item.is_active:
                        item.is_active = False
                        hidden += 1
                    continue

                row = next(r for r in spec["menu"] if r[0] == item.name)
                _, category, description, price, prep_time, photo, is_active = row
                changed = False
                if not item.description and description:
                    item.description = description
                    changed = True
                if not item.photo and photo:
                    item.photo = photo
                    changed = True
                if item.prep_time_minutes != prep_time:
                    item.prep_time_minutes = prep_time
                    changed = True
                if item.price == 0:
                    item.price = Decimal(price)
                    changed = True
                if item.category != category:
                    item.category = category
                    changed = True
                if changed:
                    filled += 1

                # Активность канонического варианта выравниваем, но не включаем
                # то, что заведение осознанно скрыло и что уже заказывали.
                ordered = db.scalar(
                    select(OrderItem.id).where(OrderItem.menu_item_id == item.id).limit(1)
                )
                item.is_active = True if not ordered else item.is_active

        db.commit()

        without_photo = db.scalars(
            select(MenuItem).where(MenuItem.is_active.is_(True), MenuItem.photo.is_(None))
        ).all()
        print(f"скрыто дублей: {hidden}")
        print(f"дополнено карточек: {filled}")
        print(f"активных блюд без фото: {len(without_photo)}")
        for item in without_photo[:6]:
            print("   ", item.name)
        print("заведений:", db.query(Establishment).count(),
              "| блюд:", db.query(MenuItem).count())
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
