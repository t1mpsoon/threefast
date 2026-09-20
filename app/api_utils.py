"""Вспомогательные функции HTTP-слоя: клиентский IP, сборка ответов, rate limiting."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import Request

from app.config import settings
from app.errors import RateLimitError
from app.models.order import Order, OrderStatus, PaymentMethod, PaymentStatus
from app.schemas.order import OrderItemOut, OrderStatusResponse, StaffOrderOut
from app.schemas.slot import SlotOut
from app.services.slot_service import SlotView
from app.utils.rate_limit import RateLimiter

# Ограничение создания заказов с одного IP (раздел 2.14 ТЗ).
order_rate_limiter = RateLimiter(limit=settings.rate_limit_orders_per_minute)

# Поиск заказа по коду: короткий код легко перебирать, поэтому считаем отдельно
# именно промахи. Гость, который ищет свой заказ, ошибается пару раз; скрипт,
# подбирающий чужие, не попадает почти никогда.
order_lookup_limiter = RateLimiter(limit=12, window_seconds=300)


def client_ip(request: Request) -> str:
    """IP гостя для ограничений.

    Заголовку `X-Forwarded-For` верим только когда приложение стоит за прокси,
    которому доверяем (`TRUST_PROXY_HEADERS`). Иначе его подставит кто угодно,
    и лимит на заказы обходится одной строкой в запросе.
    """
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# Подбор пароля: считаем только неудачные входы с одного адреса.
login_limiter = RateLimiter(limit=10, window_seconds=300)


def ensure_lookup_allowed(request: Request) -> None:
    """Не даёт перебирать коды заказов.

    Считаем только промахи (см. `note_lookup_miss`), поэтому проверка здесь —
    это вопрос «не набрал ли адрес слишком много неудач», а не «не превысил ли
    он частоту». Гость, который открывает свой заказ, лимит не тратит вообще.
    """
    wait = order_lookup_limiter.retry_after(f"lookup:{client_ip(request)}")
    if wait:
        raise RateLimitError(
            "Слишком много попыток подобрать код заказа. "
            f"Проверьте код и попробуйте через {wait} сек."
        )


def note_lookup_miss(request: Request) -> None:
    """Промах по коду приближает блокировку — в отличие от найденного заказа."""
    order_lookup_limiter.penalize(f"lookup:{client_ip(request)}")


def as_float(value: Decimal | float | int | None) -> float:
    return round(float(value or 0), 2)


def slot_to_schema(view: SlotView) -> SlotOut:
    return SlotOut(
        slot_datetime=view.slot_datetime,
        available=view.available,
        free_places=view.free_places,
        capacity=view.capacity,
        booked_count=view.booked_count,
        is_too_soon=view.is_too_soon,
        label=view.label,
        discount_percent=view.discount_percent,
    )


PROGRESS_STEPS = {
    OrderStatus.CONFIRMED: 1,
    OrderStatus.IN_PROGRESS: 2,
    OrderStatus.READY: 3,
    OrderStatus.PICKED_UP: 4,
}


def progress_step(status: OrderStatus) -> int:
    """Шаг индикатора «Принят → Готовится → Готово → Выдано»."""
    return PROGRESS_STEPS.get(status, 0)


def status_message(order: Order, *, now: datetime | None = None) -> str | None:
    """Пояснение для гостя, если заказ не в обычном потоке."""
    status = order.status_enum
    if status is OrderStatus.CANCELLED:
        return "Заказ отменён. Если это ошибка — оформите новый заказ."
    if status is OrderStatus.EXPIRED:
        return (
            "Заказ не был получен вовремя и снят с выдачи. "
            "Пожалуйста, оформите новый заказ."
        )
    return None


def payment_title(order: Order) -> str:
    """Как гость платит: словами, а не значением из базы."""
    try:
        method = PaymentMethod(order.payment_method)
    except ValueError:  # pragma: no cover — защита от старых записей
        return "Оплата при получении"
    return {
        PaymentMethod.CASH_ON_PICKUP: "Наличными при получении",
        PaymentMethod.CARD_ON_PICKUP: "Картой при получении",
    }[method]


def order_to_status_schema(order: Order) -> OrderStatusResponse:
    status = order.status_enum
    return OrderStatusResponse(
        order_code=order.order_code,
        status=status.value,
        status_title=status.title,
        status_tone=status.tone,
        slot_datetime=order.slot.slot_datetime,
        created_at=order.created_at,
        ready_at=order.ready_at,
        picked_up_at=order.picked_up_at,
        total_amount=as_float(order.total_amount),
        payment_status=PaymentStatus(order.payment_status).title,
        payment_method=order.payment_method,
        payment_method_title=payment_title(order),
        guest_name=order.guest_name,
        note=order.note,
        items=[OrderItemOut.model_validate(item) for item in order.items],
        progress_step=progress_step(status),
        is_active=status.is_active,
        message=status_message(order),
    )


def order_to_staff_schema(order: Order) -> StaffOrderOut:
    status = order.status_enum
    return StaffOrderOut(
        id=order.id,
        order_code=order.order_code,
        guest_name=order.guest_name,
        guest_phone=order.guest_phone,
        status=status.value,
        status_title=status.title,
        status_tone=status.tone,
        total_amount=as_float(order.total_amount),
        items_count=order.items_count,
        slot_datetime=order.slot.slot_datetime,
        created_at=order.created_at,
        ready_at=order.ready_at,
        version=order.version,
        note=order.note,
        allowed_transitions=sorted(
            transition.value for transition in order.can_transition_to
        ),
        items=[OrderItemOut.model_validate(item) for item in order.items],
    )
