"""Аналитика: подтверждение критериев успеха кейса (Ф-9 раздела 2.3 ТЗ).

Метрика «среднее время ожидания» считается как разница между временем слота
(когда гость должен был получить заказ) и фактическим временем выдачи
(picked_up_at). Это именно ожидание на месте, а не время с момента заказа.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.establishment import Establishment
from app.models.order import Order, OrderStatus
from app.models.time_slot import TimeSlot
from app.repositories.menu_repository import EstablishmentRepository
from app.utils.time_utils import local_today

WAIT_TARGET_MINUTES = 2.0  # критерий успеха кейса: 20 мин -> 2 мин
THROUGHPUT_TARGET_PERCENT = 25.0  # критерий успеха кейса: рост >= 25%


@dataclass(slots=True)
class AnalyticsResult:
    period: str
    date_from: date
    date_to: date
    orders_count: int = 0
    picked_up_count: int = 0
    lost_orders_count: int = 0
    average_wait_minutes: float | None = None
    wait_target_minutes: float = WAIT_TARGET_MINUTES
    throughput_target_percent: float = THROUGHPUT_TARGET_PERCENT
    wait_target_met: bool = False
    baseline_orders_count: int = 0
    baseline_wait_minutes: float = 20.0
    throughput_growth_percent: float | None = None
    capacity_per_hour: int = 0
    message: str | None = None
    wait_samples: list[float] = field(default_factory=list)


@dataclass(slots=True)
class PlatformResult:
    """Сводка по всем заведениям: для администратора сервиса."""

    period: str
    date_from: date
    date_to: date
    places_total: int = 0
    active_places: int = 0
    orders_count: int = 0
    picked_up_count: int = 0
    lost_orders_count: int = 0
    revenue: float = 0.0
    average_wait_minutes: float | None = None
    wait_target_minutes: float = WAIT_TARGET_MINUTES
    wait_target_met: bool = False
    places_by_status: dict[str, int] = field(default_factory=dict)
    message: str | None = None


class AnalyticsService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.establishments = EstablishmentRepository(db)
    # ── Периоды ────────────────────────────────────────────────────────────
    @staticmethod
    def resolve_period(period: str, *, today: date | None = None) -> tuple[date, date]:
        reference = today or local_today()
        normalized = (period or "day").strip().lower()
        if normalized in {"day", "today", "день"}:
            return reference, reference
        if normalized in {"week", "7d", "неделя"}:
            return reference - timedelta(days=6), reference
        if normalized in {"month", "30d", "месяц"}:
            return reference - timedelta(days=29), reference
        raise ValueError("period должен быть day, week или month")

    # ── Основной расчёт ────────────────────────────────────────────────────
    def build_report(
        self, establishment_id: int, period: str = "day", *, today: date | None = None
    ) -> AnalyticsResult:
        establishment: Establishment | None = self.establishments.get(establishment_id)
        if establishment is None:
            raise ValueError("Заведение не найдено")

        date_from, date_to = self.resolve_period(period, today=today)
        orders = self._orders_for_range(establishment_id, date_from, date_to)

        result = AnalyticsResult(
            period=period,
            date_from=date_from,
            date_to=date_to,
            baseline_orders_count=establishment.baseline_orders_per_day,
            baseline_wait_minutes=float(establishment.baseline_wait_minutes or 20),
            capacity_per_hour=self._capacity_per_hour(establishment),
        )

        # Заказы cancelled/expired не искажают среднее время ожидания,
        # но учитываются отдельно как «потерянные» (edge case Ф-9).
        active_orders = [
            order for order in orders if order.status != OrderStatus.CANCELLED.value
        ]
        result.orders_count = len(active_orders)
        result.lost_orders_count = sum(
            1
            for order in orders
            if order.status in {OrderStatus.CANCELLED.value, OrderStatus.EXPIRED.value}
        )

        waits: list[float] = []
        for order in orders:
            if order.status != OrderStatus.PICKED_UP.value or order.picked_up_at is None:
                continue
            wait = self.compute_wait_minutes(order)
            if wait is not None:
                waits.append(wait)

        result.picked_up_count = len(waits)
        result.wait_samples = waits
        if waits:
            result.average_wait_minutes = round(sum(waits) / len(waits), 2)
            result.wait_target_met = result.average_wait_minutes <= WAIT_TARGET_MINUTES
        else:
            result.message = "Недостаточно данных: за период нет выданных заказов"

        result.throughput_growth_percent = self.throughput_growth(
            result.orders_count, result.baseline_orders_count, days=result_days(date_from, date_to)
        )
        return result

    @staticmethod
    def compute_wait_minutes(order: Order) -> float | None:
        """Ожидание = picked_up_at − время слота (в минутах)."""
        if order.picked_up_at is None or order.slot is None:
            return None
        picked_up = order.picked_up_at
        if picked_up.tzinfo is None:
            picked_up = picked_up.replace(tzinfo=timezone.utc)
        picked_up_local = picked_up.astimezone().replace(tzinfo=None)
        wait = (picked_up_local - order.slot.slot_datetime).total_seconds() / 60
        return max(wait, 0.0)

    @staticmethod
    def throughput_growth(
        orders_count: int, baseline_orders_count: int, *, days: int = 1
    ) -> float | None:
        """% роста пропускной способности относительно эталона «до внедрения».

        Эталон вводится администратором вручную — система не знает истории до себя.
        """
        if baseline_orders_count <= 0:
            return None
        baseline = baseline_orders_count * max(days, 1)
        return round((orders_count - baseline) / baseline * 100, 1)

    @staticmethod
    def _capacity_per_hour(establishment: Establishment) -> int:
        """Теоретическая пропускная способность, заказов в час."""
        if establishment.slot_duration_minutes <= 0:
            return 0
        slots_per_hour = 60 / establishment.slot_duration_minutes
        return int(slots_per_hour * establishment.slot_capacity)

    def _orders_for_range(
        self, establishment_id: int, date_from: date, date_to: date
    ) -> list[Order]:
        start = datetime.combine(date_from, time.min)
        end = datetime.combine(date_to, time.max)
        stmt = (
            select(Order)
            .join(TimeSlot, Order.slot_id == TimeSlot.id)
            .options(joinedload(Order.slot), joinedload(Order.items))
            .where(
                Order.establishment_id == establishment_id,
                TimeSlot.slot_datetime >= start,
                TimeSlot.slot_datetime <= end,
            )
        )
        return list(self.db.scalars(stmt).unique())

    # ── Данные для графиков админ-панели ──────────────────────────────────
    def hourly_load(
        self, establishment_id: int, day: date
    ) -> list[tuple[str, int]]:
        """Распределение заказов по часам — наглядно показывает сглаживание пиков."""
        orders = self._orders_for_range(establishment_id, day, day)
        buckets: dict[int, int] = {}
        for order in orders:
            hour = order.slot.slot_datetime.hour
            buckets[hour] = buckets.get(hour, 0) + 1
        return [(f"{hour:02d}:00", buckets.get(hour, 0)) for hour in sorted(buckets)]

    # ── Сводка по всей платформе (администратор сервиса) ──────────────────
    def build_platform_report(
        self, period: str = "day", *, today: date | None = None
    ) -> PlatformResult:
        """Сводка по всем заведениям сразу: сколько заказов, как ждут гости.

        Нужна администратору сервиса: он отвечает за платформу целиком, а не
        за одну точку, поэтому фильтра по establishment_id здесь нет.
        """
        date_from, date_to = self.resolve_period(period, today=today)
        establishment_ids = [place.id for place in self.establishments.list_all()]

        result = PlatformResult(
            period=period,
            date_from=date_from,
            date_to=date_to,
            places_total=len(establishment_ids),
        )
        if not establishment_ids:
            result.message = "В сервисе пока нет заведений"
            return result

        orders = self._orders_for_range_all(establishment_ids, date_from, date_to)
        result.orders_count = len(orders)
        result.picked_up_count = sum(
            1 for order in orders if order.status == OrderStatus.PICKED_UP.value
        )
        result.lost_orders_count = sum(
            1
            for order in orders
            if order.status in {OrderStatus.CANCELLED.value, OrderStatus.EXPIRED.value}
        )
        result.revenue = round(sum(float(order.total_amount) for order in orders), 2)
        result.active_places = len({order.establishment_id for order in orders})
        result.places_by_status = self._places_by_status(orders, establishment_ids)

        waits = [
            wait for wait in (self.compute_wait_minutes(order) for order in orders)
            if wait is not None
        ]
        if waits:
            result.average_wait_minutes = round(sum(waits) / len(waits), 1)
            result.wait_target_met = result.average_wait_minutes <= WAIT_TARGET_MINUTES
        else:
            result.message = "Недостаточно данных: за период нет выданных заказов"

        return result

    def _orders_for_range_all(
        self, establishment_ids: list[int], date_from: date, date_to: date
    ) -> list[Order]:
        """Заказы всех заведений за период — без фильтра по одной точке."""
        start = datetime.combine(date_from, time.min)
        end = datetime.combine(date_to, time.max)
        stmt = (
            select(Order)
            .join(TimeSlot, Order.slot_id == TimeSlot.id)
            .options(joinedload(Order.slot), joinedload(Order.items))
            .where(
                Order.establishment_id.in_(establishment_ids),
                TimeSlot.slot_datetime >= start,
                TimeSlot.slot_datetime <= end,
            )
            .order_by(TimeSlot.slot_datetime, Order.id)
        )
        return list(self.db.scalars(stmt).unique())

    def _places_by_status(
        self, orders: list[Order], establishment_ids: list[int]
    ) -> dict[str, int]:
        """Сколько заведений реально принимают заказы, а сколько простаивают."""
        with_orders = {order.establishment_id for order in orders}
        return {
            "with_orders": len(with_orders),
            "idle": max(len(establishment_ids) - len(with_orders), 0),
        }


def result_days(date_from: date, date_to: date) -> int:
    return max((date_to - date_from).days + 1, 1)
