"""Тестовые заказы на сегодня: панель кухни нужно увидеть в работе. Только для разработки."""

from __future__ import annotations

import logging
import sys
from datetime import datetime, time, timedelta

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.disable(logging.CRITICAL)

from app.database import SessionLocal
from app.models.establishment import Establishment
from app.models.menu_item import MenuItem
from app.schemas.order import OrderCreateRequest
from app.services.order_service import OrderService
from app.models.order import OrderStatus


# Минимальный запас: кухня не берёт заказ, если до выдачи меньше времени
# приготовления самого долгого блюда (правило Б-1).
SAFE_LEAD_MINUTES = 22


def ahead(minutes: int) -> datetime:
    """Время выдачи не раньше, чем через SAFE_LEAD_MINUTES от сейчас."""
    return datetime.now() + timedelta(minutes=max(minutes, SAFE_LEAD_MINUTES))


def slot_at(hour: int, minute: int, day_offset: int = 0) -> datetime:
    moment = datetime.now() + timedelta(days=day_offset)
    return moment.replace(hour=hour, minute=minute, second=0, microsecond=0)


def dishes_of(place_id: int, *patterns: str) -> list[MenuItem]:
    """Находит блюда заведения по началу названия: у каждой точки своё меню."""
    db = SessionLocal()
    try:
        found = []
        for pattern in patterns:
            item = (
                db.query(MenuItem)
                .filter(MenuItem.establishment_id == place_id, MenuItem.name.like(pattern))
                .first()
            )
            if item is not None:
                found.append(item)
        return found
    finally:
        db.close()


def main() -> int:
    db = SessionLocal()
    try:
        # Демо-очередь наполняем для того заведения, чей аккаунт кухни проверяем.
        wanted = (sys.argv[1] if len(sys.argv) > 1 else "Green Bowl").strip().lower()
        place = (
            db.query(Establishment).filter(Establishment.name.ilike(f"%{wanted}%")).first()
            or db.query(Establishment).first()
        )
        # Окно работы расширяем, чтобы сегодня были доступные минуты.
        place.opens_at = time(0, 0)
        place.closes_at = time(23, 55)
        place.slot_capacity = 3
        db.commit()

        # Берём любые три активные блюда этого заведения: названия у точек разные.
        menu = (
            db.query(MenuItem)
            .filter(MenuItem.establishment_id == place.id, MenuItem.is_active.is_(True))
            .order_by(MenuItem.id)
            .limit(3)
            .all()
        )
        if len(menu) < 3:
            print(f"у заведения «{place.name}» мало блюд для демо-заказов")
            return 1
        first, second, third = menu[0], menu[1], menu[2]
        print(f"демо-очередь для «{place.name}»: {first.name}, {second.name}, {third.name}")

        # Разные гости, примечания и способы оплаты: очередь должна выглядеть живой.
        plan = [
            ("Айгерим", "+77011110001", ahead(12), [(first.id, 2)],
             None, "Без лука, пожалуйста", "card_on_pickup"),
            ("Данияр", "+77011110002", ahead(25), [(second.id, 1), (third.id, 2)],
             OrderStatus.IN_PROGRESS, None, "cash_on_pickup"),
            ("Мадина", "+77011110003", ahead(40), [(first.id, 1)],
             OrderStatus.READY, "Приборы на двоих", "card_on_pickup"),
            ("Ерасыл", "+77011110004", ahead(8), [(third.id, 1)],
             OrderStatus.READY, None, "cash_on_pickup"),
            ("Камила", "+77011110005", ahead(55), [(second.id, 2), (first.id, 1)],
             None, "Позвоните, когда будет готово", "cash_on_pickup"),
            ("Нурлан", "+77011110006", ahead(70), [(third.id, 3)],
             OrderStatus.IN_PROGRESS, None, "card_on_pickup"),
        ]

        service = OrderService(db)
        made = []
        for index, (name, phone, at, items, target, note, payment) in enumerate(plan):
            moment = at.replace(second=0, microsecond=0)
            moment = moment.replace(minute=moment.minute - moment.minute % 5)
            payload = OrderCreateRequest(
                establishment_id=place.id,
                slot_datetime=moment,
                guest_name=name,
                guest_phone=phone,
                items=[{"menu_item_id": i, "quantity": q} for i, q in items],
                payment_method=payment,
                note=note,
                idempotency_key=f"demo-orders-key-{index:02d}",
            )
            try:
                created = service.create_order(payload)
            except Exception as error:
                made.append(f"{name}: не создан ({type(error).__name__})")
                continue

            order = created.order
            if target is OrderStatus.IN_PROGRESS:
                service.change_status(order.id, OrderStatus.IN_PROGRESS,
                                      expected_version=order.version,
                                      establishment_id=place.id)
            elif target is OrderStatus.READY:
                order = service.change_status(order.id, OrderStatus.IN_PROGRESS,
                                              expected_version=order.version,
                                              establishment_id=place.id)
                service.change_status(order.id, OrderStatus.READY,
                                      expected_version=order.version,
                                      establishment_id=place.id)
            made.append(f"{name}: {order.order_code} на {moment.strftime('%H:%M')}")

        print("сегодня создано:")
        for line in made:
            print("  ", line)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
