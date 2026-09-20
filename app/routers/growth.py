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
    tables: int = Query(0, ge=0, le=60, description="Сколько столов в зале: плакат для каждого"),
    table: int = Query(0, ge=0, le=60, description="Печатать только этот столик"),
    db: Session = Depends(get_db),
):
    """Печатный плакат с QR-кодом: гость сканирует и заказывает без очереди.

    Заведение выбирается прямо на странице, поэтому администратор сервиса
    печатает плакаты для любой точки, а не только для первой. Плакат бывает
    общий, на каждый стол зала или только на выбранный столик.
    """
    repository = EstablishmentRepository(db)
    establishment = repository.get(establishment_id)
    if establishment is None:
        raise NotFoundError("Заведение не найдено")

    base = str(request.base_url).rstrip("/")
    link = f"{base}/e/{establishment.id}/menu"

    if table:
        posters = [{"label": f"Стол {table}", "url": f"{link}?src=table{table}"}]
    elif tables:
        posters = [
            {"label": f"Стол {number}", "url": f"{link}?src=table{number}"}
            for number in range(1, tables + 1)
        ]
    else:
        posters = [{"label": "", "url": link}]

    return templates.TemplateResponse(
        request,
        "qr.html",
        {
            "establishment": establishment,
            # Все заведения: в списке видно, для какой точки печатается плакат.
            "places": repository.list_all(),
            "posters": posters,
            "hall_tables": tables,
            "chosen_table": table,
            **_runtime_flags(request, db),
        },
    )


@router.get("/for-business", response_class=HTMLResponse, include_in_schema=False)
def page_business(request: Request, db: Session = Depends(get_db)):
    """Лендинг для владельцев кафе: чем сервис помогает и сколько даёт."""
    return templates.TemplateResponse(
        request, "business.html", {**_runtime_flags(request, db)}
    )


@router.get("/qr", include_in_schema=False)
def qr_shortcut(
    request: Request,
    place: int | None = Query(None, ge=1, description="Заведение для плаката"),
    tables: int = Query(0, ge=0, le=60, description="Сколько столов в зале"),
    mode: str | None = Query(None, alias="print", description="one | all | tableN"),
    db: Session = Depends(get_db),
):
    """Выбор заведения и стола для QR-плаката.

    С явным заведением ссылка публичная: страница плаката открыта всем, и
    выбор в её форме тоже не должен требовать входа. Без заведения это
    короткая ссылка сотрудника — тогда ведём на его точку (администратор
    сервиса видит выбранную, а не всегда первую).
    """
    from fastapi.responses import RedirectResponse

    from app.routers.public_pages import _current_user_or_redirect

    repository = EstablishmentRepository(db)
    if place is None:
        # Без явного заведения это короткая ссылка сотрудника: ведём на его точку.
        user = _current_user_or_redirect(request, db)
        if isinstance(user, RedirectResponse):
            return user
        place = user.establishment_id
        if place is None:
            first = repository.get_first()
            if first is None:
                raise NotFoundError("Заведение не найдено")
            place = first.id

    table = 0
    chosen = (mode or "").strip().lower()
    if chosen == "one":
        tables = 0
    elif chosen == "all":
        tables = tables or 1
    elif chosen.startswith("table"):
        table = int(chosen[5:] or 0) if chosen[5:].isdigit() else 0
        tables = tables or 0

    query = [f"{key}={value}" for key, value in (("tables", tables), ("table", table)) if value]
    suffix = "?" + "&".join(query) if query else ""
    return RedirectResponse(url=f"/e/{place}/qr{suffix}", status_code=303)


@router.get("/scan", response_class=HTMLResponse, include_in_schema=False)
def page_scan(request: Request, db: Session = Depends(get_db)):
    """Сканер QR-кодов заказов для кухни и администратора сервиса."""
    from fastapi.responses import RedirectResponse

    from app.routers.public_pages import _current_user_or_redirect

    user = _current_user_or_redirect(request, db)
    if isinstance(user, RedirectResponse):
        return user
    return templates.TemplateResponse(
        request,
        "staff/scan.html",
        {"user": user, **_runtime_flags(request, db)},
    )
