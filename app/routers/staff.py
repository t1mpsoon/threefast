"""API персонала и администратора: очередь заказов, меню, слоты, аналитика (Ф-6–Ф-9)."""

from __future__ import annotations

from datetime import datetime, time as time_type

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api_utils import order_to_staff_schema
from app.database import get_db
from app.errors import NotFoundError, InputError
from app.models.establishment import Establishment
from app.models.enums import StaffRole
from app.models.order import Order, OrderStatus
from app.models.staff_user import StaffUser
from app.repositories.menu_repository import EstablishmentRepository, MenuRepository
from app.schemas.common import RecordId
from app.schemas.menu import MenuItemCreate, MenuItemOut
from app.schemas.order import (
    AnalyticsResponse,
    QueueStats,
    StaffMeOut,
    StaffOrderOut,
    StatusUpdateRequest,
    StatusUpdateResponse,
)
from app.schemas.place import (
    KitchenPasswordOut,
    ProfileOut,
    ProfileUpdateRequest,
)
from app.schemas.slot import SlotSettingsUpdate
from app.security import get_current_user, hash_password, require_admin
from app.services.analytics_service import AnalyticsService
from app.services.menu_service import MenuService
from app.services.order_service import OrderService
from app.services.slot_service import SlotService
from app.utils.codes import generate_password
from app.utils.time_utils import local_now, parse_date

router = APIRouter(prefix="/api/staff", tags=["Панель персонала"])


# ── Кто вошёл: панель должна знать заведение и права ────────────────────────
@router.get("/me", response_model=StaffMeOut, summary="Кто вошёл и за что отвечает")
def whoami(
    user: StaffUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StaffMeOut:
    """Возвращает роль и заведение сотрудника: панель показывает их в шапке,
    а кухня работает только со своими заказами (раздел 2.14 ТЗ)."""
    establishment = (
        EstablishmentRepository(db).get(user.establishment_id)
        if user.establishment_id
        else None
    )
    role = user.role_enum
    return StaffMeOut(
        username=user.username,
        role=role.value,
        role_title=role.title,
        is_admin=user.is_admin,
        is_super=user.is_super,
        establishment_id=establishment.id if establishment else None,
        establishment_name=establishment.name if establishment else "",
        establishment_address=establishment.address if establishment else "",
        cuisine=(establishment.cuisine or "") if establishment else "",
        opens_at=establishment.opens_at.strftime("%H:%M") if establishment else "",
        closes_at=establishment.closes_at.strftime("%H:%M") if establishment else "",
        slot_capacity=establishment.slot_capacity if establishment else 0,
    )


# ── Ф-6: очередь заказов ────────────────────────────────────────────────────
def _require_place(user: StaffUser) -> int:
    """Заведение сотрудника. У администратора сервиса его нет — говорим прямо.

    Без этой проверки суперадмин получал пустую очередь и думал, что заказов
    нет, хотя просто не выбрано заведение.
    """
    if user.establishment_id is None:
        raise InputError(
            "У администратора сервиса нет своего заведения. "
            "Откройте заведения и выберите точку."
        )
    return user.establishment_id


@router.get("/orders", response_model=list[StaffOrderOut], summary="Очередь заказов на день")
def list_orders(
    date: str | None = Query(default=None, description="Дата в формате YYYY-MM-DD"),
    user: StaffUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[StaffOrderOut]:
    """Активные заказы заведения, отсортированные по времени выдачи.

    Сотрудник видит только заказы своего заведения (раздел 2.14 ТЗ).
    """
    day = parse_date(date) if date else None
    if date and day is None:
        raise InputError("Неверный формат даты, ожидается YYYY-MM-DD")
    orders = OrderService(db).get_queue(_require_place(user), day)
    return [order_to_staff_schema(order) for order in orders]


@router.patch(
    "/orders/{order_id}/status",
    response_model=StatusUpdateResponse,
    summary="Изменить статус заказа",
)
def change_order_status(
    order_id: RecordId,
    payload: StatusUpdateRequest,
    user: StaffUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StatusUpdateResponse:
    """Переводит заказ в новый статус.

    Проверяются допустимость перехода (правило Б-2) и версия записи
    (optimistic locking): при одновременном изменении вторым сотрудником
    вернётся 409.
    """
    order = OrderService(db).change_status(
        order_id,
        payload.new_status,
        expected_version=payload.version,
        establishment_id=_require_place(user),
    )
    return StatusUpdateResponse(
        order_id=order.id,
        order_code=order.order_code,
        status=order.status,
        status_title=order.status_enum.title,
        version=order.version,
    )


# ── Ф-7: управление меню ────────────────────────────────────────────────────
@router.get("/menu", response_model=list[MenuItemOut], summary="Меню заведения (включая скрытые)")
def admin_menu(
    user: StaffUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[MenuItemOut]:
    _, items, _ = MenuService(db).list_menu(_require_place(user), only_active=False)
    return [MenuItemOut.model_validate(item) for item in items]


@router.post(
    "/menu",
    response_model=MenuItemOut,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить блюдо (администратор)",
)
def create_menu_item(
    payload: MenuItemCreate,
    admin: StaffUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> MenuItemOut:
    item = MenuService(db).create_item(admin.establishment_id, payload)
    return MenuItemOut.model_validate(item)


@router.put("/menu/{menu_item_id}", response_model=MenuItemOut, summary="Изменить блюдо (админ)")
def update_menu_item(
    menu_item_id: RecordId,
    payload: MenuItemCreate,
    admin: StaffUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> MenuItemOut:
    service = MenuService(db)
    item = service.menu.get(menu_item_id)
    if item is None or item.establishment_id != admin.establishment_id:
        raise NotFoundError("Блюдо не найдено")
    return MenuItemOut.model_validate(service.update_item(menu_item_id, payload))


@router.delete("/menu/{menu_item_id}", summary="Удалить или скрыть блюдо (админ)")
def delete_menu_item(
    menu_item_id: RecordId,
    admin: StaffUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Если блюдо уже встречается в заказах — оно деактивируется, история сохраняется (Ф-7)."""
    service = MenuService(db)
    item = service.menu.get(menu_item_id)
    if item is None or item.establishment_id != admin.establishment_id:
        raise NotFoundError("Блюдо не найдено")
    updated_item, deleted = service.delete_item(menu_item_id)
    return {
        "menu_item_id": menu_item_id,
        "deleted": deleted,
        "is_active": updated_item.is_active,
        "message": "Блюдо удалено из меню" if deleted else "Блюдо скрыто из меню (есть в заказах)",
    }


@router.patch("/menu/{menu_item_id}/active", response_model=MenuItemOut, summary="Скрыть/показать")
def toggle_menu_item(
    menu_item_id: RecordId,
    is_active: bool = Query(...),
    admin: StaffUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> MenuItemOut:
    service = MenuService(db)
    item = service.menu.get(menu_item_id)
    if item is None or item.establishment_id != admin.establishment_id:
        raise NotFoundError("Блюдо не найдено")
    return MenuItemOut.model_validate(service.set_active(menu_item_id, is_active))


# ── Ф-8: настройки слотов и вместимости ────────────────────────────────────
@router.get("/queue-stats", response_model=QueueStats, summary="Сводка смены на сейчас")
def queue_stats(
    user: StaffUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> QueueStats:
    """Показывает смене то, что нужно решать прямо сейчас: сколько заказов,
    что готово, где горит и когда следующий гость."""
    orders = OrderService(db).get_queue(_require_place(user), None)
    reference = local_now()

    portions = sum(order.items_count for order in orders)
    revenue = sum(float(order.total_amount) for order in orders)
    late = sum(
        1 for order in orders
        if order.status != OrderStatus.READY.value
        and _seconds_left(order, reference) is not None
        and _seconds_left(order, reference) <= 300
    )
    upcoming = [
        order for order in orders
        if order.status in {OrderStatus.CONFIRMED.value, OrderStatus.IN_PROGRESS.value}
        and _seconds_left(order, reference) is not None
    ]
    upcoming.sort(key=lambda order: order.slot.slot_datetime)

    place_id = _require_place(user)
    establishment = EstablishmentRepository(db).get(place_id)
    busiest_at, busiest_load = SlotService(db).busiest_window(place_id, reference)

    next_order = upcoming[0] if upcoming else None
    return QueueStats(
        total=len(orders),
        confirmed=sum(1 for o in orders if o.status == OrderStatus.CONFIRMED.value),
        in_progress=sum(1 for o in orders if o.status == OrderStatus.IN_PROGRESS.value),
        ready=sum(1 for o in orders if o.status == OrderStatus.READY.value),
        late=late,
        portions=portions,
        revenue=round(revenue, 2),
        next_at=next_order.slot.slot_datetime.isoformat() if next_order else None,
        next_code=next_order.order_code if next_order else None,
        next_left_seconds=_seconds_left(next_order, reference) if next_order else None,
        busiest_at=busiest_at,
        busiest_load=busiest_load,
        capacity=establishment.slot_capacity if establishment else 0,
    )


def _seconds_left(order: Order | None, reference: datetime) -> int | None:
    """Сколько секунд до названной минуты заказа. None — если время уже прошло."""
    if order is None:
        return None
    moment = order.slot.slot_datetime
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=reference.tzinfo)
    left = int((moment - reference).total_seconds())
    return left if left >= 0 else None


@router.get("/settings", summary="Текущие настройки заведения")
def get_settings(user: StaffUser = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    establishment = EstablishmentRepository(db).get(_require_place(user))
    if establishment is None:
        raise NotFoundError("Заведение не найдено")
    return _settings_payload(establishment)


@router.put("/settings", summary="Изменить параметры слотов (администратор)")
def update_settings(
    payload: SlotSettingsUpdate,
    admin: StaffUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Меняет длительность слота, вместимость кухни и рабочие часы.

    Новое значение вместимости применяется к ещё не наступившим слотам;
    уже существующие брони не отменяются (edge case Ф-8).
    """
    repository = EstablishmentRepository(db)
    establishment = repository.get(admin.establishment_id)
    if establishment is None:
        raise NotFoundError("Заведение не найдено")

    opens_at = time_type.fromisoformat(payload.opens_at)
    closes_at = time_type.fromisoformat(payload.closes_at)
    if opens_at == closes_at:
        raise InputError("Время открытия и закрытия не должно совпадать")

    repository.update_settings(
        establishment,
        slot_duration_minutes=payload.slot_duration_minutes,
        slot_capacity=payload.slot_capacity,
        opens_at=opens_at,
        closes_at=closes_at,
        baseline_orders_per_day=payload.baseline_orders_per_day,
        baseline_wait_minutes=payload.baseline_wait_minutes,
    )
    # Вместимость обновляем только у будущих слотов: уже сделанные брони не отменяются.
    SlotService(db).slots.update_capacity_for_future(
        establishment.id, payload.slot_capacity, now=local_now()
    )
    db.commit()
    db.refresh(establishment)

    return _settings_payload(establishment)


def _settings_payload(establishment: Establishment) -> dict:
    return {
        "establishment_id": establishment.id,
        "name": establishment.name,
        "address": establishment.address,
        "opens_at": establishment.opens_at.strftime("%H:%M"),
        "closes_at": establishment.closes_at.strftime("%H:%M"),
        "slot_duration_minutes": establishment.slot_duration_minutes,
        "slot_capacity": establishment.slot_capacity,
        "baseline_orders_per_day": establishment.baseline_orders_per_day,
        "baseline_wait_minutes": float(establishment.baseline_wait_minutes or 0),
        "capacity_per_hour": AnalyticsService._capacity_per_hour(establishment),
    }


# ── Профиль заведения: то, что видит гость ──────────────────────────────────
@router.get("/profile", response_model=ProfileOut, summary="Профиль своего заведения")
def get_profile(
    admin: StaffUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ProfileOut:
    establishment = EstablishmentRepository(db).get(admin.establishment_id)
    if establishment is None:
        raise NotFoundError("Заведение не найдено")
    return ProfileOut(**_profile_payload(establishment))


@router.put("/profile", response_model=ProfileOut, summary="Изменить профиль (администратор)")
def update_profile(
    payload: ProfileUpdateRequest,
    admin: StaffUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ProfileOut:
    """Адрес, фото, кухня и часы работы своего заведения.

    Идентификатор заведения берём из текущего пользователя: администратор
    не может править чужую точку. Вместимость и шаг слотов здесь не меняются —
    для них есть отдельная ручка настроек.
    """
    repository = EstablishmentRepository(db)
    establishment = repository.get(admin.establishment_id)
    if establishment is None:
        raise NotFoundError("Заведение не найдено")

    if payload.address is not None:
        establishment.address = payload.address or None
    if payload.cuisine is not None:
        establishment.cuisine = payload.cuisine or None
    if payload.photo is not None:
        establishment.photo = payload.photo or None

    if payload.opens_at and payload.closes_at:
        opens_at = time_type.fromisoformat(payload.opens_at)
        closes_at = time_type.fromisoformat(payload.closes_at)
        if opens_at == closes_at:
            raise InputError("Время открытия и закрытия не должно совпадать")
        establishment.opens_at = opens_at
        establishment.closes_at = closes_at
    elif payload.opens_at or payload.closes_at:
        raise InputError("Часы работы меняются парой: укажите и открытие, и закрытие")

    db.commit()
    db.refresh(establishment)
    return ProfileOut(**_profile_payload(establishment))


def _profile_payload(establishment: Establishment) -> dict:
    return {
        "establishment_id": establishment.id,
        "name": establishment.name,
        "address": establishment.address or "",
        "cuisine": establishment.cuisine or "",
        "photo": establishment.photo or "",
        "rating": float(establishment.rating or 0),
        "opens_at": establishment.opens_at.strftime("%H:%M"),
        "closes_at": establishment.closes_at.strftime("%H:%M"),
    }


# ── Пароль кухни: администратор заведения меняет его сам ────────────────────
@router.post(
    "/kitchen-password",
    response_model=KitchenPasswordOut,
    summary="Сбросить пароль кухне (администратор)",
)
def reset_kitchen_password(
    admin: StaffUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> KitchenPasswordOut:
    """Выдаёт новый пароль кухонному аккаунту своего заведения.

    Администратор точки решает это сам, без обращения к администратору сервиса.
    Пароль меняется только у роли `staff` того же заведения: учётная запись
    администратора не затрагивается. Прежний пароль восстановить нельзя —
    в базе хранится только хеш.
    """
    kitchen = db.scalars(
        select(StaffUser).where(
            StaffUser.establishment_id == admin.establishment_id,
            StaffUser.role == StaffRole.STAFF.value,
        ).order_by(StaffUser.id)
    ).first()
    if kitchen is None:
        raise NotFoundError("У заведения нет кухонного аккаунта")

    password = generate_password()
    kitchen.password_hash = hash_password(password)
    db.commit()

    return KitchenPasswordOut(
        username=kitchen.username,
        password=password,
        message=(
            "Новый пароль кухни готов. Он показывается один раз — передайте его "
            "смене, прежний больше не действует."
        ),
    )


# ── Ф-9: аналитика ──────────────────────────────────────────────────────────
@router.get("/analytics", response_model=AnalyticsResponse, summary="Метрики (администратор)")
def analytics(
    period: str = Query(default="day", pattern="^(day|week|month)$"),
    admin: StaffUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AnalyticsResponse:
    """Среднее время ожидания и рост пропускной способности относительно эталона."""
    report = AnalyticsService(db).build_report(admin.establishment_id, period)
    return AnalyticsResponse(
        period=report.period,
        date_from=report.date_from.isoformat(),
        date_to=report.date_to.isoformat(),
        orders_count=report.orders_count,
        picked_up_count=report.picked_up_count,
        lost_orders_count=report.lost_orders_count,
        average_wait_minutes=report.average_wait_minutes,
        wait_target_met=report.wait_target_met,
        baseline_orders_count=report.baseline_orders_count,
        baseline_wait_minutes=report.baseline_wait_minutes,
        throughput_growth_percent=report.throughput_growth_percent,
        capacity_per_hour=report.capacity_per_hour,
        message=report.message,
    )


# ── Сканер QR: поиск заказа по коду и смена статуса ─────────────────────────
def _order_for_scan(code: str, user: StaffUser, db: Session):
    """Заказ по коду из QR. Кухня видит только свои заказы, супер-админ — любые."""
    from app.utils.codes import is_valid_order_code, normalize_order_code

    if not is_valid_order_code(code):
        raise InputError("Это не похоже на номер заказа. Номер выглядит так: EX-3467")
    order = OrderService(db).get_order_by_code(normalize_order_code(code))
    if not user.is_super and order.establishment_id != user.establishment_id:
        # Чужой заказ не раскрываем: для кухни его как будто нет.
        raise NotFoundError("Заказ с таким номером в вашем заведении не найден")
    return order


@router.get(
    "/orders/by-code/{code}",
    response_model=StaffOrderOut,
    summary="Найти заказ по коду (для сканера QR)",
)
def find_order_by_code(
    code: str,
    user: StaffUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StaffOrderOut:
    return order_to_staff_schema(_order_for_scan(code, user, db))


@router.patch(
    "/orders/by-code/{code}/status",
    response_model=StatusUpdateResponse,
    summary="Изменить статус заказа по коду (для сканера QR)",
)
def change_status_by_code(
    code: str,
    payload: StatusUpdateRequest,
    user: StaffUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StatusUpdateResponse:
    order = _order_for_scan(code, user, db)
    updated = OrderService(db).change_status(
        order.id,
        payload.new_status,
        expected_version=payload.version,
        establishment_id=order.establishment_id,
    )
    return StatusUpdateResponse(
        order_id=updated.id,
        order_code=updated.order_code,
        status=updated.status,
        status_title=updated.status_enum.title,
        version=updated.version,
    )
