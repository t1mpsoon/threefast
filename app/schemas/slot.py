"""Pydantic-схемы временных слотов (раздел 2.8 ТЗ, правила А-1, Б-1)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SlotOut(BaseModel):
    """Слот для гостя: время, доступность и число свободных мест."""

    model_config = ConfigDict(from_attributes=True)

    slot_datetime: datetime
    available: bool
    free_places: int
    capacity: int
    booked_count: int
    # Доп. поля для UI: почему слот недоступен.
    is_too_soon: bool = False
    label: str = ""

    @property
    def time_label(self) -> str:
        return self.slot_datetime.strftime("%H:%M")


class SlotListResponse(BaseModel):
    establishment_id: int
    establishment_name: str
    date: str
    slots: list[SlotOut] = Field(default_factory=list)
    available_count: int = 0
    message: str | None = None
    min_prep_time_minutes: int = 0


class SlotSettingsUpdate(BaseModel):
    """Настройки расчёта слотов (Ф-8)."""

    slot_duration_minutes: int = Field(ge=1, le=240)
    slot_capacity: int = Field(ge=1, le=1000)
    opens_at: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    closes_at: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    baseline_orders_per_day: int = Field(default=0, ge=0, le=100000)
    baseline_wait_minutes: float = Field(default=20.0, ge=0, le=600)
