"""Схемы управления заведениями (раздел супер-администратора)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import RecordId
from app.utils.codes import generate_password  # noqa: F401  (реэкспорт для тестов)


class PlaceAdminOut(BaseModel):
    """Заведение глазами супер-администратора: с доступами и составом."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    address: str
    cuisine: str
    photo: str
    rating: float
    opens_at: str
    closes_at: str
    slot_duration_minutes: int
    slot_capacity: int
    dishes_count: int
    admin_login: str | None = None
    staff_login: str | None = None
    logins: list[str] = Field(default_factory=list)
    created_at: str | None = None


class PlaceCreateRequest(BaseModel):
    """Новое заведение: имя, адрес, часы и вместимость кухни."""

    name: str = Field(min_length=2, max_length=100)
    address: str = Field(default="", max_length=200)
    cuisine: str = Field(default="", max_length=50)
    photo: str = Field(default="", max_length=200)
    rating: float = Field(default=4.8, ge=0, le=5)
    opens_at: str = Field(default="09:00", pattern=r"^\d{2}:\d{2}$")
    closes_at: str = Field(default="21:00", pattern=r"^\d{2}:\d{2}$")
    slot_duration_minutes: int = Field(default=5, ge=5, le=60)
    slot_capacity: int = Field(default=3, ge=1, le=50)
    baseline_orders_per_day: int = Field(default=35, ge=0, le=5000)
    baseline_wait_minutes: float = Field(default=20, ge=1, le=240)
    # Если пароль не задан — сгенерируем и покажем один раз.
    admin_password: str | None = Field(default=None, min_length=8, max_length=72)

    @field_validator("name", "address", "cuisine", "photo")
    @classmethod
    def _clean(cls, value: str) -> str:
        return " ".join((value or "").split())


class PlaceUpdateRequest(BaseModel):
    """Правка заведения: любое поле можно не передавать."""

    name: str | None = Field(default=None, min_length=2, max_length=100)
    address: str | None = Field(default=None, max_length=200)
    cuisine: str | None = Field(default=None, max_length=50)
    photo: str | None = Field(default=None, max_length=200)
    rating: float | None = Field(default=None, ge=0, le=5)
    # Строгая проверка: «99:99» проходит по \d{2}:\d{2}, но time.fromisoformat
    # на нём падает — раньше это давало 500 вместо понятного 422.
    opens_at: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    closes_at: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    slot_duration_minutes: int | None = Field(default=None, ge=5, le=60)
    slot_capacity: int | None = Field(default=None, ge=1, le=50)
    baseline_orders_per_day: int | None = Field(default=None, ge=0, le=5000)
    baseline_wait_minutes: float | None = Field(default=None, ge=1, le=240)


class PlacePasswordOut(BaseModel):
    """Ответ с доступами: пароль показывается один раз."""

    place: PlaceAdminOut
    admin_login: str | None = None
    staff_login: str | None = None
    password: str
    message: str

class ProfileOut(BaseModel):
    """Профиль заведения: то, что видит гость в карточке."""

    establishment_id: RecordId
    name: str
    address: str
    cuisine: str
    photo: str
    rating: float
    opens_at: str
    closes_at: str


class ProfileUpdateRequest(BaseModel):
    """Правка профиля. Размеры слотов и вместимость сюда не входят.

    Эти параметры меняются отдельной ручкой настроек: у них другая логика —
    вместимость применяется только к будущим слотам.
    """

    address: str | None = Field(default=None, max_length=200)
    cuisine: str | None = Field(default=None, max_length=50)
    photo: str | None = Field(default=None, max_length=200)
    opens_at: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    closes_at: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")

    @field_validator("address", "cuisine", "photo")
    @classmethod
    def _clean(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return " ".join(value.split())


class KitchenPasswordOut(BaseModel):
    """Новый пароль кухонного аккаунта: показывается один раз."""

    username: str
    password: str
    message: str

class PlatformAnalyticsResponse(BaseModel):
    """Сводка по всей платформе для администратора сервиса."""

    period: str
    date_from: str
    date_to: str
    places_total: int = 0
    active_places: int = 0
    idle_places: int = 0
    orders_count: int = 0
    picked_up_count: int = 0
    lost_orders_count: int = 0
    revenue: float = 0.0
    average_wait_minutes: float | None = None
    wait_target_minutes: float = 2.0
    wait_target_met: bool = False
    message: str | None = None
