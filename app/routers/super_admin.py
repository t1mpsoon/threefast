"""Управление заведениями: супер-администратор заводит точки и выдаёт доступ.

Раздел нужен, чтобы подключить новый ресторан без правки кода: создать заведение,
получить логин и пароль для его смены, при необходимости сменить пароль.
"""

from __future__ import annotations

from datetime import time as time_type
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import ConflictError, InputError, NotFoundError
from app.models.establishment import Establishment
from app.models.staff_user import StaffUser
from app.schemas.common import RecordId
from app.schemas.place import (
    PlaceAdminOut,
    PlatformAnalyticsResponse,
    PlaceCreateRequest,
    PlacePasswordOut,
    PlaceUpdateRequest,
)
from app.security import hash_password, require_super
from app.services.analytics_service import AnalyticsService
from app.utils.codes import generate_password

router = APIRouter(prefix="/api/super", tags=["Управление заведениями"])


def _login_for(place: Establishment) -> str:
    """Логин администратора заведения.

    Схема одна на весь проект: `place-<номер>`. Раньше здесь был отдельный
    генератор «из названия», и карточка показывала логин, которого в базе нет —
    у заведений из начальных данных он вовсе оставался пустым.
    """
    return f"place-{place.id}"


def _ops_login_for(place: Establishment) -> str:
    """Логин смены кухни: `kitchen-<номер>`.

    Для трёх точек из начальных данных он читаемый (kitchen-bowl и т. д.) —
    их создаёт app/init_db.py, и логин там задан явно.
    """
    known = {
        1: "kitchen-central",
        2: "kitchen-bowl",
        3: "kitchen-coffee",
    }
    return known.get(place.id, f"kitchen-{place.id}")


def _place_payload(db: Session, place: Establishment) -> PlaceAdminOut:
    users = list(
        db.scalars(select(StaffUser).where(StaffUser.establishment_id == place.id))
    )
    # Берём аккаунты по схеме именования, а не «первый попавшийся»: под
    # старым правилом карточка показывала администратором точки того, кто
    # просто раньше завёлся.
    expected_admin = f"place-{place.id}"
    expected_staff = f"kitchen-{place.id}"
    admin = next((user for user in users if user.username == expected_admin), None)
    if admin is None:
        admin = next((user for user in users if user.is_admin), None)
    staff = next((user for user in users if user.username == expected_staff), None)
    if staff is None:
        staff = next((user for user in users if not user.is_admin), None)
    dishes = len(place.menu_items)
    return PlaceAdminOut(
        id=place.id,
        name=place.name,
        address=place.address or "",
        cuisine=place.cuisine or "",
        photo=place.photo or "",
        rating=float(place.rating or 0),
        opens_at=place.opens_at.strftime("%H:%M"),
        closes_at=place.closes_at.strftime("%H:%M"),
        slot_duration_minutes=place.slot_duration_minutes,
        slot_capacity=place.slot_capacity,
        dishes_count=dishes,
        admin_login=admin.username if admin else None,
        staff_login=(staff.username if staff else None) or _ops_login_for(place),
        logins=[user.username for user in users],
        created_at=place.created_at.isoformat() if place.created_at else None,
    )


def _apply_times(place: Establishment, opens_at: str, closes_at: str) -> None:
    try:
        opens = time_type.fromisoformat(opens_at)
        closes = time_type.fromisoformat(closes_at)
    except ValueError as error:
        raise InputError("Время указывается в формате ЧЧ:ММ") from error
    if opens == closes:
        raise InputError("Время открытия и закрытия не должно совпадать")
    place.opens_at = opens
    place.closes_at = closes


@router.get("/places", response_model=list[PlaceAdminOut], summary="Все заведения с доступами")
def list_places(
    _: StaffUser = Depends(require_super),
    db: Session = Depends(get_db),
) -> list[PlaceAdminOut]:
    places = list(db.scalars(select(Establishment).order_by(Establishment.id)))
    return [_place_payload(db, place) for place in places]


@router.post(
    "/places",
    response_model=PlacePasswordOut,
    status_code=status.HTTP_201_CREATED,
    summary="Завести заведение и выдать доступ",
)
def create_place(
    payload: PlaceCreateRequest,
    _: StaffUser = Depends(require_super),
    db: Session = Depends(get_db),
) -> PlacePasswordOut:
    """Создаёт заведение и два аккаунта: администратора точки и смену кухни.

    Пароль возвращается один раз — в базе он хранится только хешем.
    """
    exists = db.scalars(
        select(Establishment).where(Establishment.name == payload.name)
    ).first()
    if exists is not None:
        raise ConflictError(f"Заведение «{payload.name}» уже есть")

    place = Establishment(
        name=payload.name,
        address=payload.address or None,
        cuisine=payload.cuisine or None,
        photo=payload.photo or None,
        rating=Decimal(str(payload.rating)),
        slot_duration_minutes=payload.slot_duration_minutes,
        slot_capacity=payload.slot_capacity,
        baseline_orders_per_day=payload.baseline_orders_per_day,
        baseline_wait_minutes=Decimal(str(payload.baseline_wait_minutes)),
    )
    _apply_times(place, payload.opens_at, payload.closes_at)
    db.add(place)
    db.flush()

    password = payload.admin_password or generate_password()
    admin_login = _login_for(place)
    staff_login = _ops_login_for(place)
    for username, role in ((admin_login, "admin"), (staff_login, "staff")):
        taken = db.scalars(select(StaffUser).where(StaffUser.username == username)).first()
        if taken is not None:
            raise ConflictError(f"Логин {username} уже занят — переименуйте заведение")
        db.add(
            StaffUser(
                establishment_id=place.id,
                username=username,
                password_hash=hash_password(password),
                role=role,
            )
        )
    db.commit()
    db.refresh(place)

    return PlacePasswordOut(
        place=_place_payload(db, place),
        admin_login=admin_login,
        staff_login=staff_login,
        password=password,
        message=(
            f"Заведение «{place.name}» создано. Сохраните пароль: "
            "он показывается один раз и в базе не хранится."
        ),
    )


@router.put("/places/{place_id}", response_model=PlaceAdminOut, summary="Изменить заведение")
def update_place(
    place_id: RecordId,
    payload: PlaceUpdateRequest,
    _: StaffUser = Depends(require_super),
    db: Session = Depends(get_db),
) -> PlaceAdminOut:
    place = db.get(Establishment, place_id)
    if place is None:
        raise NotFoundError("Заведение не найдено")

    if payload.name and payload.name != place.name:
        other = db.scalars(
            select(Establishment).where(
                Establishment.name == payload.name, Establishment.id != place_id
            )
        ).first()
        if other is not None:
            raise ConflictError(f"Заведение «{payload.name}» уже есть")
        place.name = payload.name

    if payload.address is not None:
        place.address = payload.address or None
    if payload.cuisine is not None:
        place.cuisine = payload.cuisine or None
    if payload.photo is not None:
        place.photo = payload.photo or None
    if payload.rating is not None:
        place.rating = Decimal(str(payload.rating))
    if payload.slot_duration_minutes is not None:
        place.slot_duration_minutes = payload.slot_duration_minutes
    if payload.slot_capacity is not None:
        place.slot_capacity = payload.slot_capacity
    if payload.baseline_orders_per_day is not None:
        place.baseline_orders_per_day = payload.baseline_orders_per_day
    if payload.baseline_wait_minutes is not None:
        place.baseline_wait_minutes = Decimal(str(payload.baseline_wait_minutes))
    if payload.opens_at and payload.closes_at:
        _apply_times(place, payload.opens_at, payload.closes_at)

    db.commit()
    db.refresh(place)
    return _place_payload(db, place)


@router.get(
    "/analytics",
    response_model=PlatformAnalyticsResponse,
    summary="Сводка по всей платформе (администратор сервиса)",
)
def platform_analytics(
    period: str = Query(default="day", pattern="^(day|week|month)$"),
    _: StaffUser = Depends(require_super),
    db: Session = Depends(get_db),
) -> PlatformAnalyticsResponse:
    """Суммарные показатели по всем заведениям: заказы, ожидание, активность.

    Фильтра по заведению здесь нет намеренно: администратор сервиса смотрит
    на платформу целиком, а не на одну точку.
    """
    report = AnalyticsService(db).build_platform_report(period)
    return PlatformAnalyticsResponse(
        period=report.period,
        date_from=report.date_from.isoformat(),
        date_to=report.date_to.isoformat(),
        places_total=report.places_total,
        active_places=report.active_places,
        idle_places=report.places_by_status.get("idle", 0),
        orders_count=report.orders_count,
        picked_up_count=report.picked_up_count,
        lost_orders_count=report.lost_orders_count,
        revenue=report.revenue,
        average_wait_minutes=report.average_wait_minutes,
        wait_target_minutes=report.wait_target_minutes,
        wait_target_met=report.wait_target_met,
        message=report.message,
    )


@router.post(
    "/places/{place_id}/password",
    response_model=PlacePasswordOut,
    summary="Сменить пароль доступа заведения",
)
def reset_password(
    place_id: RecordId,
    _: StaffUser = Depends(require_super),
    db: Session = Depends(get_db),
) -> PlacePasswordOut:
    """Выдаёт новый пароль смене и администратору заведения.

    Прежний пароль восстановить нельзя: в базе лежит только хеш.
    """
    place = db.get(Establishment, place_id)
    if place is None:
        raise NotFoundError("Заведение не найдено")

    users = list(
        db.scalars(select(StaffUser).where(StaffUser.establishment_id == place.id))
    )
    if not users:
        raise NotFoundError("У заведения нет аккаунтов — создайте их заново")

    password = generate_password()
    for user in users:
        user.password_hash = hash_password(password)
    db.commit()

    admin = next((user for user in users if user.is_admin), None)
    return PlacePasswordOut(
        place=_place_payload(db, place),
        admin_login=admin.username if admin else None,
        staff_login=_ops_login_for(place),
        password=password,
        message="Новый пароль выдан всей смене заведения. Прежний больше не действует.",
    )
