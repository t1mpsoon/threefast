"""Pydantic-схемы заказа (раздел 2.8 ТЗ, правила А-2, В-1, Б-2)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import RecordId
from app.models.order import OrderStatus, PaymentMethod
from app.utils.validators import normalize_name, normalize_phone


class OrderItemIn(BaseModel):
    menu_item_id: RecordId = Field(gt=0)
    quantity: int = Field(ge=1, le=20, description="Количество, 1–20 (раздел 2.10 ТЗ)")


class OrderCreateRequest(BaseModel):
    """Тело POST /api/orders (шаг 3 из 3)."""

    establishment_id: RecordId = Field(gt=0)
    slot_datetime: datetime
    guest_name: str
    guest_phone: str
    items: list[OrderItemIn] = Field(min_length=1, max_length=15)
    payment_method: PaymentMethod = PaymentMethod.CASH_ON_PICKUP
    # Примечание к заказу: «без лука», «приборы на двоих». Необязательное.
    note: str | None = Field(default=None, max_length=200)
    # Столик: гость указывает сам, метка с QR-плаката подставляет номер заранее.
    table_number: int | None = Field(default=None, ge=1, le=60)
    idempotency_key: str = Field(min_length=8, max_length=64)

    @field_validator("guest_name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return normalize_name(value)

    @field_validator("note")
    @classmethod
    def _clean_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned[:200] or None

    @field_validator("guest_phone")
    @classmethod
    def _validate_phone(cls, value: str) -> str:
        return normalize_phone(value)

    @field_validator("slot_datetime")
    @classmethod
    def _normalize_slot(cls, value: datetime) -> datetime:
        return value.replace(second=0, microsecond=0, tzinfo=None)

    @field_validator("items")
    @classmethod
    def _no_duplicates(cls, value: list[OrderItemIn]) -> list[OrderItemIn]:
        if not value:
            raise ValueError("Добавьте хотя бы одно блюдо")
        identifiers = [item.menu_item_id for item in value]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Блюдо не должно повторяться в заказе — укажите количество")
        return value


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    menu_item_id: RecordId
    item_name_snapshot: str
    item_price_snapshot: float
    quantity: int

    @field_validator("item_price_snapshot", mode="before")
    @classmethod
    def _decimal_to_float(cls, value: object) -> float:
        return float(value) if isinstance(value, Decimal) else value


class OrderCreateResponse(BaseModel):
    order_id: int
    order_code: str
    status: str
    status_title: str
    total_amount: float
    slot_datetime: datetime
    payment_status: str
    guest_name: str
    # True, если заказ вернулся по повторному запросу с тем же idempotency_key.
    duplicated: bool = False


class OrderStatusResponse(BaseModel):
    """Ответ GET /api/orders/{order_code}/status — без аккаунта, по коду заказа."""

    order_code: str
    status: str
    status_title: str
    # Продолжение заголовка экрана: «Заказ EX-1234 готов!» — одна формулировка
    # на шаблон и на опрос статуса, без отдельной таблицы строк в браузере.
    status_headline: str = ""
    # Тон статуса: один и тот же на всех экранах — guest | active | done | lost.
    status_tone: str = "guest"
    slot_datetime: datetime
    created_at: datetime
    ready_at: datetime | None = None
    picked_up_at: datetime | None = None
    total_amount: float
    payment_status: str
    payment_method: str = ""
    payment_method_title: str = ""
    guest_name: str
    note: str | None = None
    # Столик гостя: null — заказ на вынос.
    table_number: int | None = None
    items: list[OrderItemOut] = Field(default_factory=list)
    # Прогресс для индикатора «Принят → Готовится → Готово → Выдано».
    progress_step: int = 0
    is_active: bool = True
    message: str | None = None


class StaffOrderOut(BaseModel):
    """Заказ в очереди персонала (Ф-6)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    order_code: str
    guest_name: str
    guest_phone: str
    status: str
    status_title: str
    status_tone: str = "guest"
    total_amount: float
    items_count: int
    slot_datetime: datetime
    created_at: datetime
    ready_at: datetime | None = None
    version: int
    note: str | None = None
    # Столик нужен смене, чтобы вынести заказ, а не выкликивать номер.
    table_number: int | None = None
    allowed_transitions: list[str] = Field(default_factory=list)
    items: list[OrderItemOut] = Field(default_factory=list)


class StaffMeOut(BaseModel):
    """Кто вошёл и за какое заведение отвечает.

    У администратора сервиса заведения нет: он работает со всеми сразу,
    поэтому поля заведения пустые.
    """

    username: str
    role: str
    role_title: str
    is_admin: bool
    is_super: bool = False
    establishment_id: RecordId | None = None
    establishment_name: str = ""
    establishment_address: str = ""
    cuisine: str = ""
    opens_at: str = ""
    closes_at: str = ""
    slot_capacity: int = 0


class QueueStats(BaseModel):
    """Сводка смены: что происходит в очереди прямо сейчас."""

    total: int = 0
    confirmed: int = 0
    in_progress: int = 0
    ready: int = 0
    late: int = 0
    portions: int = 0
    revenue: float = 0.0
    next_at: str | None = None
    next_code: str | None = None
    next_left_seconds: int | None = None
    busiest_at: str | None = None
    busiest_load: int = 0
    capacity: int = 0


class StatusUpdateRequest(BaseModel):
    """PATCH /api/staff/orders/{id}/status с optimistic locking (раздел 2.8 ТЗ)."""

    new_status: OrderStatus
    version: int = Field(ge=1)

    @field_validator("new_status")
    @classmethod
    def _reject_terminal_as_target(cls, value: OrderStatus) -> OrderStatus:
        # Допустимость перехода (в том числе «Выдан» и «Отменён») проверяет
        # сервис по таблице ALLOWED_TRANSITIONS: здесь запрещать нельзя,
        # иначе кухня не сможет выдать или отменить заказ.
        return value


class StatusUpdateResponse(BaseModel):
    order_id: int
    order_code: str
    status: str
    status_title: str
    version: int


class AnalyticsResponse(BaseModel):
    """Метрики выполнения критериев успеха кейса (Ф-9)."""

    period: str
    date_from: str
    date_to: str
    orders_count: int
    picked_up_count: int
    lost_orders_count: int
    average_wait_minutes: float | None = None
    average_wait_target_minutes: float = 2.0
    wait_target_met: bool = False
    baseline_orders_count: int = 0
    baseline_wait_minutes: float = 20.0
    throughput_growth_percent: float | None = None
    capacity_per_hour: int = 0
    message: str | None = None
