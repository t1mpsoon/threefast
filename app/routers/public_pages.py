"""HTML-страницы: клиентский флоу из 3 шагов и панели персонала/администратора.

Клиентские страницы не требуют входа — это прямое требование кейса.
Панели защищены JWT-авторизацией (cookie ставится при входе на /login).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import BASE_DIR, settings
from app.database import SessionLocal, get_db
from app.errors import AppError, AuthenticationError, NotFoundError, PermissionDeniedError
from app.logging_utils import get_logger
from app.models.enums import StaffRole
from app.models.staff_user import StaffUser
from app.repositories.menu_repository import EstablishmentRepository
from app.repositories.staff_repository import StaffRepository
from app.security import (
    TOKEN_COOKIE_NAME,
    decode_access_token,
    get_current_user,
    require_admin,
)
from app.services.analytics_service import AnalyticsService
from app.services.menu_service import MenuService
from app.services.order_service import OrderService
from app.services.slot_service import SlotService
from app.utils.time_utils import (
    format_day_ru,
    format_slot,
    format_slot_full,
    humanize_slot,
    local_now,
    local_today,
)

logger = get_logger("pages")

templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


def format_money(value: object) -> str:
    """Сумма с разделителем разрядов: 2 200 ₸ (узкий неразрывный пробел).

    Дублирует app.js::money, чтобы сервер и клиент печатали числа одинаково.
    """
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return "0 ₸"
    text = f"{number:,.2f}" if round(number, 2) % 1 else f"{number:,.0f}"
    return text.replace(",", "\u2009") + " ₸"


# Фильтры для шаблонов
templates.env.filters["money"] = format_money
templates.env.filters["slot_time"] = format_slot
templates.env.filters["slot_full"] = format_slot_full
templates.env.filters["humanize_slot"] = humanize_slot
templates.env.filters["day_ru"] = format_day_ru
def _static_version() -> str:
    """Отпечаток статики: самая свежая правка файла в app/static.

    Нужен, чтобы браузер не держал старый скрипт после правки. Без него
    страница могла прийти новая, а `sheet_time.js` — из кеша, и кнопки
    молчали: скрипт искал элементы, которых в новой разметке уже нет.
    """
    static_dir = BASE_DIR / "app" / "static"
    try:
        newest = max(
            (path.stat().st_mtime_ns for path in static_dir.rglob("*") if path.is_file()),
            default=0,
        )
    except OSError:
        newest = 0
    return str(newest or 1)


# Значение считаем один раз при импорте: подставлять в шаблон функцию нельзя —
# Jinja напечатает её представление вместо версии.
STATIC_VERSION = _static_version()


templates.env.globals.update(
    app_title=settings.app_title,
    current_year=lambda: local_today().year,
    max_days_ahead=settings.max_booking_days_ahead,
    static_version=STATIC_VERSION,
    # Для страницы входа: сколько живёт сессия с галочкой и без неё.
    remember_days=settings.jwt_remember_days,
    session_hours=max(1, settings.jwt_expire_minutes // 60),
)

router = APIRouter(tags=["Страницы"])


def _first_establishment(db: Session):
    establishment = EstablishmentRepository(db).get_first()
    if establishment is None:
        raise NotFoundError("Заведение не найдено. Запустите python -m app.init_db")
    return establishment


def _runtime_flags(request: Request, db: Session | None = None) -> dict:
    """Данные для шапки и подвала страницы.

    Кроме факта входа отдаём самого сотрудника: шапка показывает, кто на смене,
    и предлагает выход, а администратору сервиса — ссылку на заведения вместо
    смены, куда его всё равно не пустят. Сессия берётся из cookie, поэтому
    страницы остаются доступны без JS.
    """
    token = request.cookies.get(TOKEN_COOKIE_NAME)
    user = None
    if token:
        session = db
        opened = False
        if session is None:
            session = SessionLocal()
            opened = True
        try:
            payload = decode_access_token(token)
            user = StaffRepository(session).get(int(payload.get("sub", 0)))
        except Exception:  # noqa: BLE001 — битый или просроченный токен: считаем гостем
            user = None
        finally:
            if opened:
                session.close()

    return {
        # Cookie без живого пользователя (истёк срок, аккаунт удалён) — это гость.
        "is_authenticated": user is not None,
        "current_user": user,
    }


# ── Клиентский флоу ─────────────────────────────────────────────────────────
@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def page_places(request: Request, db: Session = Depends(get_db)):
    """Главный экран: список заведений с фото, рейтингом и загрузкой кухни."""
    return templates.TemplateResponse(
        request,
        "places.html",
        {**_runtime_flags(request, db)},
    )


@router.get("/e/{establishment_id}/menu", response_class=HTMLResponse, include_in_schema=False)
def page_menu(establishment_id: int, request: Request, db: Session = Depends(get_db)):
    """Меню заведения. Выбор времени и оформление — шторками поверх экрана."""
    establishment, items, categories = MenuService(db).list_menu(establishment_id)
    return templates.TemplateResponse(
        request,
        "menu.html",
        {
            "establishment": establishment,
            "items": items,
            "categories": categories,
            "step": 1,
            "today": local_today().isoformat(),
            **_runtime_flags(request, db),
        },
    )


@router.get("/e/{establishment_id}/slots", response_class=HTMLResponse, include_in_schema=False)
def page_slots(establishment_id: int, request: Request, db: Session = Depends(get_db)):
    """Старые адреса шагов ведут на меню: выбор идёт шторками, а не страницами."""
    establishment = SlotService(db).get_establishment(establishment_id)
    return RedirectResponse(url=f"/e/{establishment.id}/menu", status_code=307)


@router.get("/e/{establishment_id}/confirm", response_class=HTMLResponse, include_in_schema=False)
def page_confirm(establishment_id: int, request: Request, db: Session = Depends(get_db)):
    """Старый адрес шага подтверждения — тоже на меню."""
    establishment = SlotService(db).get_establishment(establishment_id)
    return RedirectResponse(url=f"/e/{establishment.id}/menu", status_code=307)


@router.get("/order", response_class=HTMLResponse, include_in_schema=False)
def page_order_status(
    request: Request,
    code: str | None = None,
    fresh: str | None = None,
    db: Session = Depends(get_db),
):
    """Экран заказа: доступен по прямой ссылке без входа.

    Параметр `fresh` включается сразу после оформления — тогда показываем
    анимацию галочки и «Заказ принят».
    """
    order = None
    error = None
    if code:
        from app.utils.codes import is_valid_order_code, normalize_order_code

        if is_valid_order_code(code):
            try:
                order = OrderService(db).get_order_by_code(normalize_order_code(code))
            except NotFoundError as exc:
                error = exc.message
        else:
            error = "Код заказа должен состоять из 4 символов, например EX-3467"

    return templates.TemplateResponse(
        request,
        "order_status.html",
        {
            "order": order,
            "code": code,
            "error": error,
            "fresh": fresh == "1",
            "share_text": (
                f"Заказ {order.order_code} принят, заберу в "
                f"{order.slot.slot_datetime:%H:%M}"
                if order is not None
                else ""
            ),
            **_runtime_flags(request, db),
        },
    )


# ── Вход персонала ──────────────────────────────────────────────────────────
@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
def page_login(request: Request, next: str | None = None):
    return templates.TemplateResponse(
        request,
        "login.html",
        {"next_url": next or "", "error": None},
    )


# ── Панели ──────────────────────────────────────────────────────────────────
def _current_user_or_redirect(request: Request, db: Session) -> StaffUser | RedirectResponse:
    try:
        return get_current_user(request, db)
    except AuthenticationError as exc:
        logger.info("Неавторизованный доступ к панели: %s", exc.message)
        target = request.url.path
        return RedirectResponse(url=f"/login?next={target}", status_code=303)


@router.get("/staff", response_class=HTMLResponse, include_in_schema=False)
def page_staff_queue(request: Request, db: Session = Depends(get_db)):
    """Ф-6: очередь заказов для сотрудника кухни/кассы."""
    user = _current_user_or_redirect(request, db)
    if isinstance(user, RedirectResponse):
        return user
    # Администратор сервиса не относится ни к одному заведению: очередь смены
    # ему нечего показывать, его рабочий экран — список заведений.
    if user.can_manage_places and user.establishment_id is None:
        return RedirectResponse(url="/super", status_code=303)
    return templates.TemplateResponse(
        request,
        "staff/queue.html",
        {
            "user": user,
            "role_title": StaffRole(user.role).title,
            "today": local_today().isoformat(),
            "now": local_now(),
            **_runtime_flags(request, db),
        },
    )


@router.get("/super", response_class=HTMLResponse, include_in_schema=False)
def page_super_places(request: Request, db: Session = Depends(get_db)):
    """Заведения сервиса: завести точку и выдать ей доступ."""
    user = _current_user_or_redirect(request, db)
    if isinstance(user, RedirectResponse):
        return user
    if not user.can_manage_places:
        raise PermissionDeniedError("Раздел доступен только администратору сервиса")
    return templates.TemplateResponse(
        request,
        "super/places.html",
        {
            "user": user,
            "role_title": StaffRole(user.role).title,
            **_runtime_flags(request, db),
        },
    )


@router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
def page_admin_menu(request: Request, db: Session = Depends(get_db)):
    """Администратора ведём в ту же панель: меню, настройки и аналитика там же."""
    user = _current_user_or_redirect(request, db)
    if isinstance(user, RedirectResponse):
        return user
    if user.role != StaffRole.ADMIN.value:
        raise PermissionDeniedError("Раздел доступен только администратору заведения")
    return RedirectResponse(url="/staff", status_code=303)


@router.get("/admin/analytics", response_class=HTMLResponse, include_in_schema=False)
def page_admin_analytics(
    request: Request,
    period: str = "day",
    admin: StaffUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Ф-9: дашборд подтверждения критериев успеха."""
    if period not in {"day", "week", "month"}:
        period = "day"
    analytics_service = AnalyticsService(db)
    report = analytics_service.build_report(admin.establishment_id, period)
    establishment = EstablishmentRepository(db).get(admin.establishment_id)
    return templates.TemplateResponse(
        request,
        "staff/analytics.html",
        {
            "user": admin,
            "role_title": StaffRole(admin.role).title,
            "establishment": establishment,
            "report": report,
            "period": period,
            "hourly_load": analytics_service.hourly_load(admin.establishment_id, local_today()),
            "today": local_today().isoformat(),
            **_runtime_flags(request, db),
        },
    )


# ── Страницы ошибок ─────────────────────────────────────────────────────────
async def error_page(request: Request, exc: AppError) -> HTMLResponse:
    """Человекочитаемая страница ошибки вместо traceback (раздел 2.11 ТЗ)."""
    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "status_code": exc.status_code,
            "message": exc.message,
            # Ошибку видит и гость, и сотрудник: шапка должна знать, кто это.
            **_runtime_flags(request),
        },
        status_code=exc.status_code,
    )
