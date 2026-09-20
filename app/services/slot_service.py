"""Расчёт доступных слотов (правила А-1, Б-1, Г-1 раздела 2.6 ТЗ)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.errors import InputError, NotFoundError, SlotUnavailableError
from app.models.establishment import Establishment
from app.repositories.menu_repository import EstablishmentRepository
from app.repositories.slot_repository import SlotRepository
from app.utils.time_utils import combine, format_slot, local_now, round_up_to_step


def discount_percent_for(moment: datetime) -> int:
    """Скидка (%) на выдачу в это время: вне часов пик — off-peak, в пик — 0."""
    from app.config import settings

    percent = settings.offpeak_discount_percent
    if not percent:
        return 0
    for part in settings.peak_hours.split(","):
        try:
            start, end = (int(x) for x in part.strip().split("-"))
        except ValueError:
            continue
        if start <= moment.hour < end:
            return 0
    return percent


@dataclass(slots=True)
class SlotView:
    """Представление слота для UI и API."""

    slot_datetime: datetime
    capacity: int
    booked_count: int
    available: bool
    is_too_soon: bool = False

    @property
    def free_places(self) -> int:
        return max(self.capacity - self.booked_count, 0)

    @property
    def discount_percent(self) -> int:
        return discount_percent_for(self.slot_datetime) if self.available else 0

    @property
    def label(self) -> str:
        return format_slot(self.slot_datetime)


class SlotService:
    """Сервис расчёта и проверки слотов."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.establishments = EstablishmentRepository(db)
        self.slots = SlotRepository(db)

    # ── Получение заведения ────────────────────────────────────────────────
    def get_establishment(self, establishment_id: int) -> Establishment:
        establishment = self.establishments.get(establishment_id)
        if establishment is None:
            raise NotFoundError("Заведение не найдено")
        return establishment

    # ── Алгоритм А-1 ───────────────────────────────────────────────────────
    def build_slots(
        self,
        establishment: Establishment,
        day: date,
        *,
        now: datetime | None = None,
        min_lead_minutes: int | None = None,
    ) -> list[SlotView]:
        """Генерирует сетку слотов на день по алгоритму А-1:
        прошедшие и «слишком близкие» слоты — недоступны, заполненные — заняты.
        """
        reference = now or local_now()
        lead = min_lead_minutes or 0
        grid = self._slot_times(establishment, day)
        booked = {s.slot_datetime: s for s in self.slots.list_for_day(establishment.id, day)}

        views: list[SlotView] = []
        for moment in grid:
            record = booked.get(moment)
            capacity = record.capacity if record else establishment.slot_capacity
            booked_count = record.booked_count if record else 0

            earliest_allowed = reference + timedelta(minutes=lead)
            is_too_soon = moment < earliest_allowed
            available = (not is_too_soon) and booked_count < capacity

            views.append(
                SlotView(
                    slot_datetime=moment,
                    capacity=capacity,
                    booked_count=booked_count,
                    available=available,
                    is_too_soon=is_too_soon,
                )
            )
        # Правило Г-1: сортировка по возрастанию времени.
        return sorted(views, key=lambda view: view.slot_datetime)

    def _slot_times(self, establishment: Establishment, day: date) -> list[datetime]:
        """Сетка от opens_at до closes_at с шагом slot_duration_minutes."""
        step = establishment.slot_duration_minutes
        start = combine(day, establishment.opens_at)
        end = combine(day, establishment.closes_at)
        if end <= start:  # заведение работает через полночь (например, 10:00–02:00)
            end += timedelta(days=1)
        moments: list[datetime] = []
        cursor = start
        while cursor < end:
            moments.append(cursor)
            cursor += timedelta(minutes=step)
        return moments

    # ── Публичный список слотов (Ф-3) ──────────────────────────────────────
    def list_slots(
        self,
        establishment_id: int,
        day: date,
        *,
        now: datetime | None = None,
        min_lead_minutes: int | None = None,
    ) -> tuple[Establishment, list[SlotView]]:
        establishment = self.get_establishment(establishment_id)
        views = self.build_slots(establishment, day, now=now, min_lead_minutes=min_lead_minutes)
        return establishment, views

    def validate_requested_date(self, day: date, *, now: datetime | None = None) -> None:
        """Дата в прошлом или слишком далеко в будущем — 400 (edge case раздела 2.15)."""
        reference = (now or local_now()).date()
        if day < reference:
            raise InputError("Нельзя запросить слоты на прошедшую дату")
        if day > reference + timedelta(days=settings.max_booking_days_ahead):
            raise InputError(
                f"Бронирование доступно не более чем на {settings.max_booking_days_ahead} дней вперёд"
            )

    # ── Проверка выбранного слота (правило Б-1) ────────────────────────────
    def validate_slot_choice(
        self,
        establishment: Establishment,
        slot_datetime: datetime,
        *,
        min_prep_minutes: int = 0,
        now: datetime | None = None,
    ) -> SlotView:
        """Проверяет, что слот существует в сетке, ещё не наступил и не заполнен."""
        reference = now or local_now()
        day = slot_datetime.date()
        self.validate_requested_date(day, now=reference)

        views = self.build_slots(
            establishment, day, now=reference, min_lead_minutes=min_prep_minutes
        )
        match = next((v for v in views if v.slot_datetime == slot_datetime), None)

        if match is None:
            raise InputError(
                "Выбранное время недоступно: заведение не работает в это время "
                "или время не кратно шагу слотов"
            )
        if match.is_too_soon:
            raise InputError(
                f"На это время заказ уже не успеть приготовить — выберите время "
                f"не раньше чем через {min_prep_minutes} мин."
            )
        if match.booked_count >= match.capacity:
            # 409, как задано в разделе 2.8 ТЗ: слот заняли между шагом 2 и шагом 3.
            raise SlotUnavailableError("На это время свободных мест не осталось, выберите другое")
        return match

    def busiest_window(
        self, establishment_id: int, reference: datetime | None = None
    ) -> tuple[str | None, int]:
        """Самый нагруженный час сегодня: подсказка смене, где будет горячо.

        Возвращает («14:00», 7) — час и сколько порций забронировано в нём.
        """
        moment = reference or local_now()
        establishment = self.get_establishment(establishment_id)
        buckets: dict[str, int] = {}
        for view in self.build_slots(establishment, moment.date(), now=moment):
            key = view.slot_datetime.strftime("%H:00")
            buckets[key] = buckets.get(key, 0) + view.booked_count

        if not buckets:
            return None, 0
        busiest = max(buckets.items(), key=lambda pair: pair[1])
        return (busiest[0], busiest[1]) if busiest[1] else (None, 0)

    def nearest_available(
        self,
        establishment: Establishment,
        *,
        min_lead_minutes: int = 0,
        now: datetime | None = None,
        search_days: int = 2,
    ) -> datetime | None:
        """Ближайший доступный слот — подсказка гостю."""
        reference = now or local_now()
        for offset in range(search_days + 1):
            day = reference.date() + timedelta(days=offset)
            for view in self.build_slots(
                establishment, day, now=reference, min_lead_minutes=min_lead_minutes
            ):
                if view.available:
                    return view.slot_datetime
        return None

    def resolve_default_lead_time(
        self, step_minutes: int, now: datetime | None = None
    ) -> datetime:
        """Минимально допустимое время слота: округлённое вверх «сейчас».

        Используется UI для фильтрации сетки, пока корзина не выбрана (Б-1).
        """
        reference = now or local_now()
        return round_up_to_step(reference, max(step_minutes, 1))


def slot_times_of_day(establishment: Establishment, day: date) -> list[time]:
    """Времена слотов дня без обращения к БД (для админ-панели)."""
    step = establishment.slot_duration_minutes
    start = combine(day, establishment.opens_at)
    end = combine(day, establishment.closes_at)
    if end <= start:
        end += timedelta(days=1)
    result: list[time] = []
    cursor = start
    while cursor < end:
        result.append(cursor.time())
        cursor += timedelta(minutes=step)
    return result


def min_prep_time_minutes(items: list[tuple[int, int]]) -> int:
    """Правило Б-1: минимальное время приготовления заказа = MAX по блюдам корзины."""
    return max((prep for _, prep in items), default=0)
