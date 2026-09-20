"""Unit-тесты расчёта слотов (правила А-1, Б-1, Г-1 раздела 2.6 ТЗ)."""

from __future__ import annotations

from datetime import datetime, time, timedelta

import pytest
from sqlalchemy.orm import Session

from app.errors import InputError, NotFoundError
from app.models.establishment import Establishment
from app.models.time_slot import TimeSlot
from app.services.slot_service import SlotService


def test_slot_available_when_under_capacity(db: Session, establishment: Establishment) -> None:
    """Слот с capacity=3, booked_count=2 -> доступен, свободно 1 место."""
    establishment.slot_capacity = 3
    moment = datetime.now().replace(second=0, microsecond=0) + timedelta(hours=1)
    moment = moment.replace(minute=moment.minute - moment.minute % 5)
    db.add(
        TimeSlot(
            establishment_id=establishment.id,
            slot_datetime=moment,
            capacity=3,
            booked_count=2,
        )
    )
    db.commit()

    service = SlotService(db)
    view = service.validate_slot_choice(establishment, moment)

    assert view.available is True
    assert view.free_places == 1
    assert view.booked_count == 2


def test_slot_unavailable_when_full(db: Session, establishment: Establishment) -> None:
    """Слот с capacity=3, booked_count=3 -> недоступен."""
    establishment.slot_capacity = 3
    moment = datetime.now().replace(second=0, microsecond=0) + timedelta(hours=1)
    moment = moment.replace(minute=moment.minute - moment.minute % 5)
    db.add(
        TimeSlot(
            establishment_id=establishment.id,
            slot_datetime=moment,
            capacity=3,
            booked_count=3,
        )
    )
    db.commit()

    service = SlotService(db)
    with pytest.raises(InputError):
        service.validate_slot_choice(establishment, moment)


def test_slots_sorted_by_time(db: Session, establishment: Establishment) -> None:
    """Правило Г-1: ближайший доступный слот идёт первым."""
    service = SlotService(db)
    views = service.build_slots(establishment, datetime.now().date())
    assert views == sorted(views, key=lambda view: view.slot_datetime)
    assert len(views) > 10


def test_slots_outside_working_hours_not_generated(db: Session) -> None:
    """Слоты вне рабочих часов не отображаются вовсе (edge case раздела 2.15).

    Сетка идёт от открытия до закрытия, не включая минуту закрытия: слот ровно
    в 10:00 означал бы выдачу в момент, когда точка уже закрылась.
    """
    establishment = Establishment(
        name="Утреннее кафе",
        opens_at=time(8, 0),
        closes_at=time(10, 0),
        slot_duration_minutes=30,
        slot_capacity=2,
    )
    db.add(establishment)
    db.commit()
    db.refresh(establishment)

    views = SlotService(db).build_slots(establishment, datetime.now().date())
    assert [view.slot_datetime.strftime("%H:%M") for view in views] == [
        "08:00",
        "08:30",
        "09:00",
        "09:30",
    ]
    assert all(view.slot_datetime.time() < establishment.closes_at for view in views)
    assert all(view.slot_datetime.time() >= establishment.opens_at for view in views)


def test_slot_too_soon_excluded_by_min_prep_time(db: Session, establishment) -> None:
    """Правило Б-1: слот ближе, чем время приготовления, недоступен."""
    now = datetime.now().replace(second=0, microsecond=0)
    service = SlotService(db)
    views = service.build_slots(establishment, now.date(), now=now, min_lead_minutes=60)
    soon = [view for view in views if view.slot_datetime < now + timedelta(minutes=60)]
    assert soon, "сетка должна содержать слоты внутри часа"
    assert all(not view.is_too_soon for view in views if view.available)
    assert all(not view.available for view in soon)


def test_unknown_establishment_raises_not_found(db: Session) -> None:
    with pytest.raises(NotFoundError):
        SlotService(db).get_establishment(999_999)


def test_past_date_rejected(db: Session, establishment) -> None:
    """Edge case: запрос слотов на прошедшую дату -> ошибка (400)."""
    yesterday = datetime.now().date() - timedelta(days=1)
    with pytest.raises(InputError):
        SlotService(db).validate_requested_date(yesterday)


def test_far_future_date_rejected(db: Session, establishment) -> None:
    too_far = datetime.now().date() + timedelta(days=60)
    with pytest.raises(InputError):
        SlotService(db).validate_requested_date(too_far)


def test_slot_not_multiple_of_step_rejected(db: Session, establishment) -> None:
    """Время вне сетки слотов не принимается."""
    now = datetime.now().replace(second=0, microsecond=0)
    moment = (now + timedelta(hours=2)).replace(minute=3)
    with pytest.raises(InputError):
        SlotService(db).validate_slot_choice(establishment, moment)


def test_nearest_available_slot_found(db: Session, establishment) -> None:
    now = datetime.now().replace(second=0, microsecond=0)
    nearest = SlotService(db).nearest_available(establishment, now=now)
    assert nearest is not None
    assert nearest >= now
