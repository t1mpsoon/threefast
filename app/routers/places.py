"""API витрины: список заведений для главного экрана."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.menu import HomeResponse, HomeStats, PlaceCard, PlaceListResponse, PopularDish
from app.services.place_service import PlaceService
from app.utils.time_utils import local_today

router = APIRouter(prefix="/api/establishments", tags=["Витрина"])


def _filter(cards: list[dict], cuisine: str | None, search: str | None) -> list[dict]:
    if cuisine:
        needle = cuisine.strip().lower()
        cards = [card for card in cards if (card["cuisine"] or "").lower() == needle]
    if search:
        needle = search.strip().lower()
        cards = [
            card for card in cards
            if needle in card["name"].lower() or needle in (card["address"] or "").lower()
        ]
    return cards


@router.get("", response_model=PlaceListResponse, summary="Список заведений")
def list_places(
    cuisine: str | None = Query(default=None, description="Фильтр по кухне"),
    search: str | None = Query(default=None, max_length=60, description="Поиск по названию и адресу"),
    db: Session = Depends(get_db),
) -> PlaceListResponse:
    """Карточки заведений с фото, рейтингом, загрузкой кухни и временем до готовности."""
    service = PlaceService(db)
    cards = _filter(service.list_cards(), cuisine, search)

    message = None
    if not cards:
        message = "По этому запросу ничего не нашлось. Попробуйте другую кухню или очистите поиск."

    return PlaceListResponse(
        places=[PlaceCard.model_validate(card) for card in cards],
        cuisines=service.cuisines(),
        today=local_today().isoformat(),
        message=message,
    )


@router.get("/home", response_model=HomeResponse, summary="Главный экран целиком")
def home(
    cuisine: str | None = Query(default=None, description="Фильтр по кухне"),
    search: str | None = Query(default=None, max_length=60, description="Поиск по названию и адресу"),
    db: Session = Depends(get_db),
) -> HomeResponse:
    """Один запрос для главного экрана: сводка, популярные блюда и заведения.

    Сводка считается по всем заведениям, а список и популярное — с учётом фильтра.
    """
    service = PlaceService(db)
    all_cards = service.list_cards()
    visible = _filter(all_cards, cuisine, search)

    return HomeResponse(
        stats=HomeStats.model_validate(service.home_stats(all_cards)),
        popular=[PopularDish.model_validate(dish) for dish in service.popular_dishes()],
        places=[PlaceCard.model_validate(card) for card in visible],
        cuisines=service.cuisines(),
        today=local_today().isoformat(),
        message=None if visible else "Ничего не нашлось — попробуйте другую кухню.",
    )
