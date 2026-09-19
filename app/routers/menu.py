"""API меню: GET /api/establishments/{id}/menu (Ф-1, раздел 2.8 ТЗ)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.common import RecordId
from app.schemas.menu import EstablishmentBrief, MenuItemOut, MenuResponse
from app.services.menu_service import MenuService

router = APIRouter(prefix="/api/establishments", tags=["Меню"])


@router.get("/{establishment_id}/menu", response_model=MenuResponse, summary="Меню заведения")
def get_menu(establishment_id: RecordId, db: Session = Depends(get_db)) -> MenuResponse:
    """Возвращает активные блюда заведения, сгруппированные по категориям.

    Публичный эндпоинт: регистрация гостю не нужна (ограничение кейса).
    """
    establishment, items, categories = MenuService(db).list_menu(establishment_id)
    return MenuResponse(
        establishment=EstablishmentBrief.model_validate(establishment),
        items=[MenuItemOut.model_validate(item) for item in items],
        categories=categories,
    )
