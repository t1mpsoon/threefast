"""Создание заказа и переходы статусов (правила А-2, Б-2, Б-3, В-1 раздела 2.6 ТЗ)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import (
    InvalidStatusTransitionError,
    NotFoundError,
    SlotUnavailableError,
    InputError,
    VersionConflictError,
)
from app.logging_utils import get_logger, mask_phone
from app.models.establishment import Establishment
from app.models.menu_item import MenuItem
from app.models.order import (
    ALLOWED_TRANSITIONS,
    Order,
    OrderStatus,
    PaymentStatus,
)
from app.models.order_item import OrderItem
from app.repositories.menu_repository import MenuRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.slot_repository import SlotRepository
from app.schemas.order import OrderCreateRequest
from app.services.slot_service import SlotService
from app.utils.codes import generate_unique_order_code
from app.utils.time_utils import local_now

logger = get_logger("order_service")


@dataclass(slots=True)
class CreatedOrder:
    order: Order
    duplicated: bool = False


class OrderService:
    """Бизнес-логика заказа: сумма, идемпотентность, резервирование слота, статусы."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.orders = OrderRepository(db)
        self.menu = MenuRepository(db)
        self.slots = SlotRepository(db)
        self.slot_service = SlotService(db)

    # ── Правило В-1 ────────────────────────────────────────────────────────
    @staticmethod
    def calculate_total(positions: list[tuple[Decimal, int]]) -> Decimal:
        """Сумма заказа = Σ(цена × количество), округление до копеек."""
        total = sum((Decimal(price) * quantity for price, quantity in positions), Decimal("0"))
        return total.quantize(Decimal("0.01"))

    # ── Алгоритм создания заказа (раздел 3.4 ТЗ) ───────────────────────────
    def create_order(
        self, payload: OrderCreateRequest, *, now: datetime | None = None
    ) -> CreatedOrder:
        reference = now or local_now()

        # Шаг 1. Идемпотентность: повторный запрос возвращает тот же заказ.
        existing = self.orders.get_by_idempotency_key(payload.idempotency_key)
        if existing is not None:
            logger.warning(
                "Повторный запрос заказа по idempotency_key=%s -> %s",
                payload.idempotency_key[:8],
                existing.order_code,
            )
            return CreatedOrder(order=existing, duplicated=True)

        establishment = self.slot_service.get_establishment(payload.establishment_id)

        # Шаг 2. Валидация блюд и расчёт суммы на актуальных ценах.
        menu_items = self._resolve_menu_items(payload, establishment)
        positions = [
            (menu_items[item.menu_item_id].price, item.quantity) for item in payload.items
        ]
        total_amount = self.calculate_total(positions)
        max_prep = max(menu_items[item.menu_item_id].prep_time_minutes for item in payload.items)

        # Шаг 3. Проверка слота (правило Б-1: успеть приготовить).
        self.slot_service.validate_slot_choice(
            establishment,
            payload.slot_datetime,
            min_prep_minutes=max_prep,
            now=reference,
        )

        # Шаг 4. Резервирование места в слоте (правило А-2, атомарный UPDATE).
        slot = self.slots.try_reserve(
            establishment.id, payload.slot_datetime, establishment.slot_capacity
        )
        if slot is None:
            logger.warning(
                "Гонка за слот: заведение=%s слот=%s заполнен",
                establishment.id,
                payload.slot_datetime,
            )
            self.db.rollback()
            raise SlotUnavailableError()

        # Шаг 5. Создание заказа со снапшотом цен (правило В-1).
        order = Order(
            order_code=generate_unique_order_code(self.orders.code_exists),
            establishment_id=establishment.id,
            slot_id=slot.id,
            guest_name=payload.guest_name,
            guest_phone=payload.guest_phone,
            note=payload.note,
            status=OrderStatus.CONFIRMED.value,
            total_amount=total_amount,
            payment_method=payload.payment_method.value,
            payment_status=PaymentStatus.PENDING.value,
            idempotency_key=payload.idempotency_key,
            version=1,
            created_at=datetime.now(timezone.utc),
        )
        items = [
            OrderItem(
                menu_item_id=item.menu_item_id,
                item_name_snapshot=menu_items[item.menu_item_id].name,
                item_price_snapshot=menu_items[item.menu_item_id].price,
                quantity=item.quantity,
            )
            for item in payload.items
        ]
        try:
            self.orders.create(order, items)
            self.db.commit()
        except IntegrityError:
            # Уникальный индекс idempotency_key: параллельный дубль того же запроса.
            self.db.rollback()
            duplicate = self.orders.get_by_idempotency_key(payload.idempotency_key)
            if duplicate is not None:
                logger.warning("Параллельный дубль заказа по idempotency_key погашен")
                return CreatedOrder(order=duplicate, duplicated=True)
            raise
        except Exception:
            self.db.rollback()
            logger.exception("Не удалось создать заказ для %s", establishment.name)
            raise

        self.db.refresh(order)
        logger.info(
            "Создан заказ %s: заведение=%s, слот=%s, сумма=%s, телефон=%s",
            order.order_code,
            establishment.id,
            order.slot.slot_datetime.strftime("%Y-%m-%d %H:%M"),
            order.total_amount,
            mask_phone(order.guest_phone),
        )
        return CreatedOrder(order=order)

    def _resolve_menu_items(
        self, payload: OrderCreateRequest, establishment: Establishment
    ) -> dict[int, MenuItem]:
        """Проверяет, что все блюда существуют, принадлежат заведению и активны."""
        identifiers = [item.menu_item_id for item in payload.items]
        found = {item.id: item for item in self.menu.get_many(identifiers)}

        missing = [identifier for identifier in identifiers if identifier not in found]
        if missing:
            raise NotFoundError("Блюдо не найдено в меню заведения")

        for identifier in identifiers:
            item = found[identifier]
            if item.establishment_id != establishment.id:
                raise NotFoundError("Блюдо не найдено в меню заведения")
            if not item.is_active:
                raise InputError(f"Блюдо «{item.name}» сейчас недоступно для заказа")
        return found

    # ── Статусы (правило Б-2) ──────────────────────────────────────────────
    @staticmethod
    def allowed_transitions(status: OrderStatus) -> frozenset[OrderStatus]:
        return ALLOWED_TRANSITIONS[status]

    def change_status(
        self,
        order_id: int,
        new_status: OrderStatus,
        *,
        expected_version: int,
        establishment_id: int,
        now: datetime | None = None,
    ) -> Order:
        """Меняет статус с проверкой допустимости перехода и optimistic locking."""
        reference = now or local_now()
        order = self.orders.get(order_id)
        if order is None or order.establishment_id != establishment_id:
            raise NotFoundError("Заказ не найден")

        current = order.status_enum
        if new_status not in ALLOWED_TRANSITIONS[current]:
            logger.warning(
                "Отклонён недопустимый переход статуса %s: %s -> %s",
                order.order_code,
                current.value,
                new_status.value,
            )
            raise InvalidStatusTransitionError(
                f"Нельзя перевести заказ из «{current.title}» в «{new_status.title}»"
            )

        if order.version != expected_version:
            raise VersionConflictError()

        if not self.orders.update_status_atomic(
            order_id, new_status=new_status, expected_version=expected_version
        ):
            raise VersionConflictError()

        # bulk-UPDATE'ы (статус, version, ready_at, picked_up_at) обходят identity map,
        # поэтому объект устаревает целиком: сбрасываем его перед перечитыванием,
        # иначе в ответ и в тесты попали бы старые значения полей.
        self.db.expire(order)

        utc_moment = datetime.now(timezone.utc)
        if new_status is OrderStatus.READY:
            self.orders.mark_ready(order_id, utc_moment)
        elif new_status is OrderStatus.PICKED_UP:
            self.orders.mark_picked_up(order_id, utc_moment)
        elif new_status is OrderStatus.CANCELLED:
            self.orders.mark_cancelled(order_id, utc_moment)
            self.slots.release(order.slot_id)
        elif new_status is OrderStatus.EXPIRED:
            self.slots.release(order.slot_id)
        elif new_status is OrderStatus.CONFIRMED:
            self.orders.clear_ready_at(order_id)

        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            logger.exception("Не удалось изменить статус заказа %s", order.order_code)
            raise

        refreshed = self.orders.get(order_id)
        if refreshed is None:  # pragma: no cover - защитная ветка
            raise NotFoundError("Заказ не найден")
        logger.info(
            "Заказ %s: статус %s -> %s (версия %s)",
            refreshed.order_code,
            current.value,
            new_status.value,
            refreshed.version,
        )
        return refreshed

    def cancel_by_guest(self, order_code: str) -> Order:
        """Отмена заказа гостем по коду до момента выдачи."""
        order = self.orders.get_by_code(order_code)
        if order is None:
            raise NotFoundError("Заказ не найден")
        if order.status_enum not in {OrderStatus.CONFIRMED, OrderStatus.IN_PROGRESS}:
            raise InvalidStatusTransitionError(
                f"Заказ уже «{order.status_enum.title}» — отменить его нельзя"
            )
        return self.change_status(
            order.id,
            OrderStatus.CANCELLED,
            expected_version=order.version,
            establishment_id=order.establishment_id,
        )

    # ── Чтение ─────────────────────────────────────────────────────────────
    def get_order_by_code(self, order_code: str) -> Order:
        order = self.orders.get_by_code(order_code)
        if order is None:
            # 404 без раскрытия деталей чужих заказов (раздел 2.14 ТЗ).
            raise NotFoundError("Заказ с таким кодом не найден")
        return order

    def get_queue(self, establishment_id: int, day=None) -> list[Order]:
        from app.utils.time_utils import local_today

        return self.orders.list_for_queue(establishment_id, day or local_today())

    # ── Scheduler-задача (правило Б-3) ─────────────────────────────────────
    def expire_stale_orders(
        self, *, now: datetime | None = None, limit_minutes: int | None = None
    ) -> int:
        """Переводит в expired заказы, которые готовы, но не востребованы N минут."""
        from sqlalchemy import select

        from app.config import settings

        threshold_minutes = limit_minutes or settings.order_expire_after_ready_minutes
        reference = now or datetime.now(timezone.utc)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)

        # Задача фоновая и может выполняться в давно живущей сессии: сбрасываем
        # кэш объектов, иначе решение примется по устаревшему ready_at.
        self.db.expire_all()

        stmt = select(Order).where(
            Order.status == OrderStatus.READY.value, Order.ready_at.is_not(None)
        )
        candidates = list(self.db.scalars(stmt))
        expired = 0
        for order in candidates:
            ready_at = order.ready_at
            if ready_at is None:  # pragma: no cover - защитная ветка
                continue
            if ready_at.tzinfo is None:
                ready_at = ready_at.replace(tzinfo=timezone.utc)
            waited_minutes = (reference - ready_at).total_seconds() / 60
            if waited_minutes < threshold_minutes:
                continue
            if not self.orders.update_status_atomic(
                order.id, new_status=OrderStatus.EXPIRED, expected_version=order.version
            ):
                continue
            self.slots.release(order.slot_id)
            expired += 1
            logger.info(
                "Заказ %s не востребован %.0f мин — статус expired",
                order.order_code,
                waited_minutes,
            )
        if expired:
            self.db.commit()
        return expired
