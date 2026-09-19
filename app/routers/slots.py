"""API слотов: GET /api/establishments/{id}/slots (Ф-3, правила А-1, Б-1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api_utils import slot_to_schema
from app.database import get_db
from app.errors import InputError
from app.schemas.common import RecordId
from app.schemas.slot import SlotListResponse
from app.services.slot_service import SlotService
from app.utils.time_utils import local_today, parse_date

router = APIRouter(prefix="/api/establishments", tags=["Слоты"])


@router.get("/{establishment_id}/slots", response_model=SlotListResponse, summary="Слоты на дату")
def get_slots(
    establishment_id: RecordId,
    date: str | None = Query(default=None, description="Дата в формате YYYY-MM-DD"),
    min_prep_minutes: int = Query(
        default=0, ge=0, le=240, description="Минимальное время приготовления корзины (правило Б-1)"
    ),
    db: Session = Depends(get_db),
) -> SlotListResponse:
    """Список слотов на дату: доступные, занятые и «слишком близкие».

    Слоты вне рабочих часов не возвращаются вовсе (edge case раздела 2.15 ТЗ).
    """
    requested = parse_date(date) if date else local_today()
    if date and requested is None:
        raise InputError("Неверный формат даты, ожидается YYYY-MM-DD")

    service = SlotService(db)
    service.validate_requested_date(requested)
    establishment, views = service.list_slots(
        establishment_id, requested, min_lead_minutes=min_prep_minutes
    )

    available = [view for view in views if view.available]
    message = None
    if not available:
        message = (
            "На этот день свободных слотов нет — попробуйте выбрать другую дату"
            if not any(not view.is_too_soon for view in views)
            else "Все слоты на этот день уже заняты, попробуйте другую дату"
        )

    return SlotListResponse(
        establishment_id=establishment.id,
        establishment_name=establishment.name,
        date=requested.isoformat(),
        slots=[slot_to_schema(view) for view in views],
        available_count=len(available),
        message=message,
        min_prep_time_minutes=min_prep_minutes,
    )
