"""Проверка атомарности резервирования слота при одновременных заказах (правило А-2).

Тест намеренно идёт на файловой SQLite с WAL и двумя разными соединениями:
именно так возникает реальная гонка, которую защищает атомарный
`UPDATE ... WHERE booked_count < capacity`.
"""

from __future__ import annotations

import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import time
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models.establishment import Establishment
from app.models.menu_item import MenuItem
from app.models.time_slot import TimeSlot
from app.repositories.slot_repository import SlotRepository
from app.schemas.order import OrderCreateRequest
from app.services.order_service import OrderService
from tests.conftest import next_local_slot, order_payload


def _make_factory(database_path: Path) -> sessionmaker[Session]:
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _pragma(dbapi_connection, _record):  # pragma: no cover - инфраструктура
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def test_concurrent_orders_do_not_overbook_slot(tmp_path: Path) -> None:
    """Слот с вместимостью 1 принимает ровно один заказ из пяти одновременных."""
    database_path = tmp_path / "concurrency.db"
    factory = _make_factory(database_path)
    moment = next_local_slot()

    with factory() as setup:
        establishment = Establishment(
            name="Конкурентное кафе",
            opens_at=time(0, 0),
            closes_at=time(23, 55),
            slot_duration_minutes=5,
            slot_capacity=1,
        )
        setup.add(establishment)
        setup.commit()
        setup.refresh(establishment)
        item = MenuItem(
            establishment_id=establishment.id,
            name="Плов",
            price=Decimal("1800.00"),
            prep_time_minutes=5,
            is_active=True,
        )
        setup.add(item)
        setup.commit()
        establishment_id, item_id = establishment.id, item.id

    def attempt(index: int) -> str:
        session = factory()
        try:
            payload = OrderCreateRequest(
                **order_payload(
                    establishment_id,
                    [(item_id, 1)],
                    moment,
                    key=f"concurrent-key-{index:02d}",
                )
            )
            OrderService(session).create_order(payload)
            return "created"
        except Exception as error:  # noqa: BLE001 - проверяем именно отказ
            return f"rejected:{type(error).__name__}"
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(attempt, range(5)))

    created = [result for result in results if result == "created"]
    assert len(created) == 1, f"слот переполнен: {results}"

    # Проигравшие обязаны получить понятный отказ, а не внутреннюю ошибку:
    # раньше гонка на новом слоте давала 500 (InvalidRequestError в ensure()).
    rejected = [result for result in results if result != "created"]
    assert all(result.startswith("rejected:") for result in rejected), results
    unexpected = [r for r in rejected
                  if r.split(":", 1)[1] not in {"SlotUnavailableError", "ConflictError",
                                                "InputError", "VersionConflictError"}]
    assert not unexpected, f"непонятный отказ при гонке: {unexpected} — {results}"

    with factory() as check:
        slot = SlotRepository(check).find(establishment_id, moment)
        assert slot is not None
        assert slot.booked_count == 1
        assert slot.capacity == 1


def test_concurrent_same_idempotency_key_creates_single_order(tmp_path: Path) -> None:
    """Одинаковый idempotency_key при гонке -> один заказ, не два."""
    database_path = tmp_path / "idempotency.db"
    factory = _make_factory(database_path)
    moment = next_local_slot()

    with factory() as setup:
        establishment = Establishment(
            name="Кафе дублей",
            opens_at=time(0, 0),
            closes_at=time(23, 55),
            slot_duration_minutes=5,
            slot_capacity=5,
        )
        setup.add(establishment)
        setup.commit()
        setup.refresh(establishment)
        item = MenuItem(
            establishment_id=establishment.id,
            name="Чай",
            price=Decimal("350.00"),
            prep_time_minutes=2,
            is_active=True,
        )
        setup.add(item)
        setup.commit()
        establishment_id, item_id = establishment.id, item.id

    payload_kwargs = order_payload(
        establishment_id, [(item_id, 1)], moment, key="same-key-for-all"
    )

    def attempt(_index: int) -> str:
        session = factory()
        try:
            OrderService(session).create_order(OrderCreateRequest(**payload_kwargs))
            return "ok"
        except Exception as error:  # noqa: BLE001
            return f"error:{type(error).__name__}"
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(attempt, range(3)))

    with factory() as check:
        from app.repositories.order_repository import OrderRepository

        queue = OrderRepository(check).list_for_queue(establishment_id, moment.date())
        assert len(queue) == 1, f"создано несколько заказов: {results}"

def test_slot_created_by_another_request_does_not_break(tmp_path: Path) -> None:
    """Слот, созданный параллельным запросом, не роняет второй запрос.

    Гонка воспроизводится точно: первый вызов `ensure` видит, что слота нет,
    и в этот момент слот создаёт «другая сессия». Раньше ветка обработки
    IntegrityError вызывала `expunge` для объекта, уже выброшенного из сессии
    откатом savepoint, и запрос падал с InvalidRequestError — то есть 500
    вместо честного ответа.
    """
    database_path = tmp_path / "slot-race.db"
    factory = _make_factory(database_path)
    moment = next_local_slot()

    with factory() as setup:
        establishment = Establishment(
            name="Гонка за слотом",
            opens_at=time(0, 0),
            closes_at=time(23, 55),
            slot_duration_minutes=5,
            slot_capacity=4,
        )
        setup.add(establishment)
        setup.commit()
        establishment_id = establishment.id

    session = factory()
    repository = SlotRepository(session)
    original_find = repository.find
    calls = {"count": 0}

    def find_with_interference(est_id: int, slot_datetime: datetime):
        """Первый поиск ничего не находит и уступает дорогу «другому запросу»."""
        calls["count"] += 1
        if calls["count"] == 1:
            with factory() as other:
                other.add(TimeSlot(
                    establishment_id=est_id,
                    slot_datetime=slot_datetime,
                    capacity=4,
                    booked_count=0,
                ))
                other.commit()
            return None
        return original_find(est_id, slot_datetime)

    repository.find = find_with_interference  # type: ignore[method-assign]
    try:
        slot = repository.ensure(establishment_id, moment, capacity=4)
    finally:
        session.close()

    assert slot is not None
    assert slot.slot_datetime == moment
    assert slot.booked_count == 0

    with factory() as check:
        found = SlotRepository(check).find(establishment_id, moment)
        assert found is not None
        assert found.id == slot.id, "вернулся не тот слот"
