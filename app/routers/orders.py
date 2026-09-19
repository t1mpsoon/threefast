"""API заказов: создание (Ф-4) и публичный статус по коду (Ф-5)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.api_utils import (
    as_float,
    client_ip,
    ensure_lookup_allowed,
    note_lookup_miss,
    order_rate_limiter,
    order_to_status_schema,
)
from app.config import settings
from app.database import get_db
from app.errors import InputError, NotFoundError, RateLimitError
from app.models.order import PaymentStatus
from app.schemas.order import OrderCreateRequest, OrderCreateResponse, OrderStatusResponse
from app.services.order_service import OrderService
from app.utils.codes import is_valid_order_code, normalize_order_code

router = APIRouter(prefix="/api/orders", tags=["Заказы"])


@router.post(
    "",
    response_model=OrderCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Создать заказ (шаг 3 из 3)",
)
def create_order(
    payload: OrderCreateRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> OrderCreateResponse:
    """Создаёт заказ гостя без регистрации.

    Повторный запрос с тем же `idempotency_key` возвращает уже созданный заказ
    (200 вместо 201) — защита от дублей при двойном клике или обрыве связи.
    """
    allowed, retry_after = order_rate_limiter.check(client_ip(request))
    if not allowed:
        raise RateLimitError(
            f"Слишком много заказов подряд. Попробуйте через {retry_after} сек."
        )

    created = OrderService(db).create_order(payload)
    order = created.order

    if created.duplicated:
        response.status_code = status.HTTP_200_OK

    return OrderCreateResponse(
        order_id=order.id,
        order_code=order.order_code,
        status=order.status,
        status_title=order.status_enum.title,
        total_amount=as_float(order.total_amount),
        slot_datetime=order.slot.slot_datetime,
        payment_status=PaymentStatus(order.payment_status).title,
        guest_name=order.guest_name,
        duplicated=created.duplicated,
    )


@router.get(
    "/{order_code}/status",
    response_model=OrderStatusResponse,
    summary="Статус заказа по коду (без аккаунта)",
)
def get_order_status(
    order_code: str,
    request: Request,
    db: Session = Depends(get_db),
) -> OrderStatusResponse:
    """Статус заказа по короткому коду.

    Код случайный, а не последовательный ID (раздел 2.14 ТЗ). Но комбинаций
    всего 390 625, поэтому одних случайных кодов мало: перебор с одного адреса
    упирается в лимит промахов — считаем именно неудачные попытки, чтобы
    обычный гость не тратил лимит на просмотр своего заказа.
    """
    if not is_valid_order_code(order_code):
        raise InputError("Код заказа должен состоять из 4 символов, например EX-3467")

    ensure_lookup_allowed(request)
    try:
        order = OrderService(db).get_order_by_code(normalize_order_code(order_code))
    except NotFoundError:
        note_lookup_miss(request)
        raise
    return order_to_status_schema(order)


@router.post(
    "/{order_code}/cancel",
    response_model=OrderStatusResponse,
    summary="Отменить заказ по коду",
)
def cancel_order(
    order_code: str,
    request: Request,
    db: Session = Depends(get_db),
) -> OrderStatusResponse:
    """Отмена заказа гостем до момента выдачи."""
    if not is_valid_order_code(order_code):
        raise InputError("Код заказа должен состоять из 4 символов, например EX-3467")

    ensure_lookup_allowed(request)
    try:
        order = OrderService(db).cancel_by_guest(normalize_order_code(order_code))
    except NotFoundError:
        note_lookup_miss(request)
        raise
    return order_to_status_schema(order)
