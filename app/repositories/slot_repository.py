"""Доступ к данным слотов (таблица time_slots, правило А-2)."""

from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.time_slot import TimeSlot


class SlotRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Чтение ─────────────────────────────────────────────────────────────
    def get(self, slot_id: int) -> TimeSlot | None:
        return self.db.get(TimeSlot, slot_id)

    def find(self, establishment_id: int, slot_datetime: datetime) -> TimeSlot | None:
        stmt = select(TimeSlot).where(
            TimeSlot.establishment_id == establishment_id,
            TimeSlot.slot_datetime == slot_datetime,
        )
        return self.db.scalars(stmt).first()

    def list_for_day(self, establishment_id: int, day: date) -> list[TimeSlot]:
        start = datetime.combine(day, time.min)
        end = datetime.combine(day, time.max)
        stmt = (
            select(TimeSlot)
            .where(
                TimeSlot.establishment_id == establishment_id,
                TimeSlot.slot_datetime >= start,
                TimeSlot.slot_datetime <= end,
            )
            .order_by(TimeSlot.slot_datetime)
        )
        return list(self.db.scalars(stmt))

    def max_slot_datetime(self, establishment_id: int) -> datetime | None:
        stmt = select(TimeSlot.slot_datetime).where(
            TimeSlot.establishment_id == establishment_id
        ).order_by(TimeSlot.slot_datetime.desc()).limit(1)
        return self.db.scalars(stmt).first()

    # ── Запись ─────────────────────────────────────────────────────────────
    def ensure(self, establishment_id: int, slot_datetime: datetime, capacity: int) -> TimeSlot:
        """Возвращает слот, создавая его при необходимости.

        Гонка двух одновременных созданий разрешается через уникальный индекс
        (establishment_id, slot_datetime): проигравший ловит IntegrityError
        и перечитывает уже созданную запись.
        """
        existing = self.find(establishment_id, slot_datetime)
        if existing is not None:
            return existing

        slot = TimeSlot(
            establishment_id=establishment_id,
            slot_datetime=slot_datetime,
            capacity=capacity,
            booked_count=0,
        )
        try:
            with self.db.begin_nested():
                self.db.add(slot)
                self.db.flush()
        except IntegrityError:
            # Слот создал кто-то другой между проверкой и вставкой. Откат
            # savepoint выбрасывает объект из сессии, поэтому убирать его
            # через expunge нельзя — это падало с InvalidRequestError и
            # превращало честную гонку в 500. Просто перечитываем запись.
            found = self.find(establishment_id, slot_datetime)
            if found is None:  # pragma: no cover - защитная ветка
                raise
            return found
        return slot

    def try_reserve(self, establishment_id: int, slot_datetime: datetime, capacity: int) -> TimeSlot:
        """Атомарно резервирует место в слоте (правило А-2).

        Проверка `booked_count < capacity` и увеличение счётчика выполняются одним
        UPDATE ... WHERE booked_count < capacity, поэтому при одновременных заказах
        превышение вместимости невозможно. Если UPDATE не затронул строк — слот занят.
        """
        slot = self.ensure(establishment_id, slot_datetime, capacity)
        result = self.db.execute(
            TimeSlot.__table__.update()
            .where(
                TimeSlot.id == slot.id,
                TimeSlot.booked_count < TimeSlot.capacity,
            )
            .values(booked_count=TimeSlot.booked_count + 1)
        )
        if result.rowcount == 0:
            return None  # type: ignore[return-value]
        self.db.expire(slot, ["booked_count"])
        self.db.refresh(slot)
        return slot

    def release(self, slot_id: int) -> None:
        """Освобождает место в слоте (отмена заказа)."""
        self.db.execute(
            TimeSlot.__table__.update()
            .where(TimeSlot.id == slot_id, TimeSlot.booked_count > 0)
            .values(booked_count=TimeSlot.booked_count - 1)
        )
        self.db.flush()

    def update_capacity_for_future(
        self, establishment_id: int, capacity: int, *, now: datetime
    ) -> int:
        """Применяет новую вместимость только к ещё не наступившим слотам (edge case Ф-8).

        Уже существующие брони не отменяются: booked_count не уменьшается.
        """
        result = self.db.execute(
            TimeSlot.__table__.update()
            .where(
                TimeSlot.establishment_id == establishment_id,
                TimeSlot.slot_datetime > now,
            )
            .values(capacity=capacity)
        )
        self.db.flush()
        return int(result.rowcount or 0)

    def reserve(self, slot: TimeSlot) -> TimeSlot:
        """Безусловное резервирование (используется в тестах и сидировании)."""
        slot.booked_count += 1
        self.db.flush()
        return slot
