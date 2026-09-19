"""Работа со временем слотов.

Слоты — это «настенное» время заведения (naive datetime), а технические метки
(created_at, ready_at, picked_up_at) хранятся в UTC. Эти две шкалы нельзя
смешивать, поэтому преобразование сосредоточено здесь.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

WEEKDAYS_RU = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
MONTHS_RU = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def local_now() -> datetime:
    """Текущее локальное время сервера (шкала слотов)."""
    return datetime.now()


def local_today() -> date:
    return local_now().date()


def combine(day: date, moment: time) -> datetime:
    return datetime.combine(day, moment)


def round_up_to_step(moment: datetime, step_minutes: int) -> datetime:
    """Округляет время вверх до шага сетки слотов (например, до 5 минут)."""
    if step_minutes <= 0:
        raise ValueError("Шаг сетки должен быть положительным")
    discard = timedelta(minutes=moment.minute % step_minutes, seconds=moment.second,
                        microseconds=moment.microsecond)
    return moment - discard + (timedelta(minutes=step_minutes) if discard else timedelta())


def format_slot(moment: datetime) -> str:
    """13:05 — время, которое видит гость."""
    return moment.strftime("%H:%M")


def format_slot_full(moment: datetime) -> str:
    return moment.strftime("%d.%m.%Y %H:%M")


def humanize_slot(moment: datetime, now: datetime | None = None) -> str:
    """«Сегодня, 13:05» / «Завтра, 09:30» / «19.09.2026, 13:05»."""
    reference = (now or local_now()).date()
    delta_days = (moment.date() - reference).days
    if delta_days == 0:
        prefix = "Сегодня"
    elif delta_days == 1:
        prefix = "Завтра"
    elif delta_days == -1:
        prefix = "Вчера"
    else:
        prefix = f"{moment.day} {MONTHS_RU[moment.month - 1]}"
    return f"{prefix}, {format_slot(moment)}"


def format_day_ru(day: date, now: datetime | None = None) -> str:
    reference = (now or local_now()).date()
    delta_days = (day - reference).days
    if delta_days == 0:
        return "Сегодня"
    if delta_days == 1:
        return "Завтра"
    return f"{WEEKDAYS_RU[day.weekday()]}, {day.day} {MONTHS_RU[day.month - 1]}"


def parse_date(raw: str | None) -> date | None:
    """Парсит YYYY-MM-DD; None, если формат неверный или дата не существует."""
    if not raw:
        return None
    try:
        return date.fromisoformat(raw.strip())
    except (ValueError, TypeError):
        return None


def parse_slot_datetime(raw: str | None) -> datetime | None:
    """Парсит datetime слота в ISO-формате (в т.ч. с 'Z' или со сдвигом)."""
    if not raw:
        return None
    value = raw.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    # Слоты живут в локальной шкале заведения — сдвиг отбрасываем.
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed.replace(second=0, microsecond=0)


def seconds_left(target: datetime, now: datetime | None = None) -> int:
    """Сколько секунд осталось до цели (может быть отрицательным)."""
    return int((target - (now or local_now())).total_seconds())
