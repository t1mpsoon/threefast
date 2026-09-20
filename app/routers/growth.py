"""Страницы для роста: QR-плакат заведения и лендинг для владельцев кафе."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import NotFoundError
from app.repositories.menu_repository import EstablishmentRepository
from app.routers.public_pages import _runtime_flags, templates

router = APIRouter(tags=["Рост"])


@router.get("/e/{establishment_id}/qr", response_class=HTMLResponse, include_in_schema=False)
def page_qr(
    request: Request,
    establishment_id: int,
    tables: int = Query(0, ge=0, le=60, description="Сколько столов: плакат для каждого"),
    db: Session = Depends(get_db),
):
    """Печатный плакат с QR-кодом: гость сканирует и заказывает без очереди."""
    establishment = EstablishmentRepository(db).get(establishment_id)
    if establishment is None:
        raise NotFoundError("Заведение не найдено")
    base = str(request.base_url).rstrip("/")
    link = f"{base}/e/{establishment.id}/menu"
    posters = [{"label": "", "url": link}] if not tables else [
        {"label": f"Стол {n}", "url": f"{link}?src=table{n}"} for n in range(1, tables + 1)
    ]
    return templates.TemplateResponse(
        request,
        "qr.html",
        {"establishment": establishment, "posters": posters, **_runtime_flags(request)},
    )


@router.get("/for-business", response_class=HTMLResponse, include_in_schema=False)
def page_business(request: Request):
    """Лендинг для владельцев кафе: чем сервис помогает и сколько даёт."""
    return templates.TemplateResponse(request, "business.html", {**_runtime_flags(request)})


@router.get("/qr", include_in_schema=False)
def qr_shortcut(request: Request, db: Session = Depends(get_db)):
    """Короткая ссылка: сотрудник попадает на QR своего заведения, остальные — на первое."""
    from fastapi.responses import RedirectResponse

    from app.routers.public_pages import _current_user_or_redirect

    user = _current_user_or_redirect(request, db)
    if isinstance(user, RedirectResponse):
        return user
    place_id = user.establishment_id
    if place_id is None:
        first = EstablishmentRepository(db).get_first()
        if first is None:
            raise NotFoundError("Заведение не найдено")
        place_id = first.id
    return RedirectResponse(url=f"/e/{place_id}/qr", status_code=303)


@router.get("/scan", response_class=HTMLResponse, include_in_schema=False)
def page_scan(request: Request, db: Session = Depends(get_db)):
    """Сканер QR-кодов заказов для кухни и администратора сервиса."""
    from fastapi.responses import RedirectResponse

    from app.routers.public_pages import _current_user_or_redirect

    user = _current_user_or_redirect(request, db)
    if isinstance(user, RedirectResponse):
        return user
    return templates.TemplateResponse(request, "staff/scan.html", {"user": user})
