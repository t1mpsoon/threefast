"""Pydantic-схемы меню (раздел 2.8 ТЗ)."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EstablishmentBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    address: str | None = None
    cuisine: str | None = None
    photo: str | None = None
    rating: float = 0.0
    reviews_count: int = 0
    opens_at: str
    closes_at: str
    slot_duration_minutes: int
    slot_capacity: int

    @field_validator("opens_at", "closes_at", mode="before")
    @classmethod
    def _format_time(cls, value: object) -> str:
        return value.strftime("%H:%M") if hasattr(value, "strftime") else str(value)

    @field_validator("rating", mode="before")
    @classmethod
    def _decimal_to_float(cls, value: object) -> float:
        return float(value) if isinstance(value, Decimal) else value


class MenuItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str | None = None
    description: str | None = None
    photo: str | None = None
    price: float
    prep_time_minutes: int
    is_active: bool

    @field_validator("price", mode="before")
    @classmethod
    def _decimal_to_float(cls, value: object) -> float:
        return float(value) if isinstance(value, Decimal) else value


class MenuResponse(BaseModel):
    establishment: EstablishmentBrief
    items: list[MenuItemOut]
    categories: list[str] = Field(default_factory=list)


class PlaceCard(BaseModel):
    """Карточка заведения в списке: фото, рейтинг, загрузка кухни, время до готовности."""

    id: int
    name: str
    address: str | None = None
    cuisine: str | None = None
    photo: str | None = None
    rating: float = 0.0
    reviews_count: int = 0
    opens_at: str
    closes_at: str
    is_open_now: bool = False
    # Ближайшее время, когда заказ будет готов, если оформить его сейчас.
    ready_in_minutes: int | None = None
    nearest_slot: str | None = None
    # Загрузка кухни для цветного бейджа: free | busy | packed | closed.
    load: str = "free"
    load_label: str = "Свободно сейчас"
    dishes_count: int = 0
    # Названия блюд: поиск ищет и по еде, а не только по вывеске.
    popular_dishes: list[str] = Field(default_factory=list)

    @field_validator("opens_at", "closes_at", mode="before")
    @classmethod
    def _format_time(cls, value: object) -> str:
        return value.strftime("%H:%M") if hasattr(value, "strftime") else str(value)

    @field_validator("rating", mode="before")
    @classmethod
    def _decimal_to_float(cls, value: object) -> float:
        return float(value) if isinstance(value, Decimal) else value


class PlaceListResponse(BaseModel):
    places: list[PlaceCard] = Field(default_factory=list)
    cuisines: list[str] = Field(default_factory=list)
    today: str = ""
    message: str | None = None


class PopularDish(BaseModel):
    """Блюдо, которое заказывают в нескольких заведениях — витрина на главной."""

    name: str
    photo: str | None = None
    description: str | None = None
    price: float = 0.0
    prep_time_minutes: int = 0
    places_count: int = 0
    place_names: list[str] = Field(default_factory=list)


class HomeStats(BaseModel):
    """Короткая сводка для главного экрана: сколько всего и как быстро."""

    places_count: int = 0
    dishes_count: int = 0
    open_now_count: int = 0
    fastest_ready_minutes: int | None = None
    # Во сколько откроется ближайшее заведение, если сейчас всё закрыто.
    opens_at: str | None = None
    average_prep_minutes: int = 0
    orders_today: int = 0
    free_slots_today: int = 0


class HomeResponse(BaseModel):
    stats: HomeStats
    popular: list[PopularDish] = Field(default_factory=list)
    places: list[PlaceCard] = Field(default_factory=list)
    cuisines: list[str] = Field(default_factory=list)
    today: str = ""
    message: str | None = None


class MenuItemCreate(BaseModel):
    """Создание/редактирование блюда в админке (валидация раздела 2.10 ТЗ)."""

    name: str = Field(min_length=2, max_length=100)
    category: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=160)
    photo: str | None = Field(default=None, max_length=200)
    price: Decimal = Field(gt=0, le=100000, decimal_places=2)
    prep_time_minutes: int = Field(ge=1, le=240)
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 2:
            raise ValueError("Название блюда должно содержать от 2 до 100 символов")
        return cleaned

    @field_validator("category")
    @classmethod
    def _clean_category(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None

    @field_validator("description")
    @classmethod
    def _clean_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None

    @field_validator("price")
    @classmethod
    def _quantize_price(cls, value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.01"))


class MenuItemUpdate(MenuItemCreate):
    """Полное обновление блюда (PUT)."""
