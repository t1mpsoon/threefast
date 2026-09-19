"""Точка входа FastAPI: роуты, статика, обработчики ошибок, запуск планировщика.

Запуск: uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import BASE_DIR, settings
from app.errors import AppError
from app.logging_utils import get_logger, setup_logging

setup_logging(settings.log_level, settings.log_path)
logger = get_logger("main")

STATIC_DIR = BASE_DIR / "app" / "static"


def _wants_html(request: Request) -> bool:
    """Запрос из браузера (ждёт страницу) или клиент API (ждёт JSON)."""
    if request.url.path.startswith("/api/"):
        return False
    accept = request.headers.get("accept", "")
    return "text/html" in accept


def _validation_details(exc: RequestValidationError) -> tuple[dict[str, str], str]:
    """Превращает ошибки Pydantic в {поле: сообщение} на русском (раздел 2.10 ТЗ)."""
    fields: dict[str, str] = {}
    for error in exc.errors():
        location = [str(part) for part in error.get("loc", ()) if part not in {"body", "query"}]
        field = ".".join(location) or "body"
        message = error.get("msg", "Некорректное значение")
        # Pydantic-сообщения вида "Value error, текст" -> оставляем только текст.
        if message.startswith("Value error, "):
            message = message[len("Value error, ") :]
        message = (
            message.replace("Field required", "Поле обязательно для заполнения")
            .replace("Input should be a valid integer", "Ожидается целое число")
            .replace("Input should be a valid decimal", "Ожидается число")
            .replace("String should have at least", "Минимальная длина —")
            .replace("String should have at most", "Максимальная длина —")
        )
        fields[field] = message
    summary = "; ".join(f"{field}: {text}" for field, text in fields.items())
    return fields, summary or "Проверьте правильность заполнения полей"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Старт/останов приложения: схема БД, начальные данные, планировщик."""
    from app.database import session_scope
    from app.init_db import create_schema, seed
    from app.schema_guard import warn_if_outdated

    create_schema()

    # Проверяем версию схемы до первого запроса: иначе отставшая база упадёт
    # позже и с трудночитаемым «no such column». В тестах схема создаётся
    # напрямую из моделей, поэтому там проверка молчит.
    if settings.seed_on_startup:
        warn_if_outdated(settings.database_url)

    if settings.seed_on_startup:
        try:
            with session_scope() as db:
                created = seed(db)
            if created:
                logger.warning(
                    "Созданы учётные записи по умолчанию (%s). Пароли смотрите в выводе "
                    "python -m app.init_db",
                    ", ".join(username for username, _ in created),
                )
        except Exception:  # pragma: no cover - зависит от состояния БД
            logger.exception("Не удалось выполнить инициализацию начальных данных")

    scheduler = None
    if settings.enable_scheduler:
        from app.services.scheduler import create_scheduler

        scheduler = create_scheduler()
        scheduler.start()
        logger.info("Планировщик запущен: авто-истечение заказов каждые 60 сек")

    logger.info(
        "%s запущен (env=%s, БД=%s)",
        settings.app_title,
        settings.app_env,
        settings.database_url,
    )
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
            logger.info("Планировщик остановлен")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_title,
        description=(
            "Сервис предзаказа еды к точному времени: заказ за 3 шага, "
            "без регистрации, выдача по коду заказа."
        ),
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if not settings.is_production else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ── Роуты ──────────────────────────────────────────────────────────────
    from app.routers import auth, menu, orders, places, slots, staff, super_admin
    from app.routers import public_pages

    app.include_router(places.router)
    app.include_router(menu.router)
    app.include_router(slots.router)
    app.include_router(orders.router)
    app.include_router(super_admin.router)
    app.include_router(auth.router)
    app.include_router(staff.router)
    app.include_router(public_pages.router)

    _register_error_handlers(app)
    return app


def _register_error_handlers(app: FastAPI) -> None:
    """Глобальные обработчики: пользователь никогда не видит traceback (раздел 2.11 ТЗ)."""

    @app.exception_handler(AppError)
    async def _domain_error(request: Request, exc: AppError):
        payload = {"detail": exc.message, "code": exc.code, **exc.details}
        if _wants_html(request):
            from app.routers.public_pages import error_page

            return await error_page(request, exc)
        return JSONResponse(status_code=exc.status_code, content=payload)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        fields, summary = _validation_details(exc)
        if _wants_html(request):
            from app.errors import InputError
            from app.routers.public_pages import error_page

            return await error_page(request, InputError(summary))
        return JSONResponse(
            status_code=422,
            content={"detail": summary, "code": "validation_error", "fields": fields},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        message = {
            404: "Страница не найдена",
            405: "Метод не поддерживается",
        }.get(exc.status_code, str(exc.detail))
        if _wants_html(request):
            from app.errors import AppError as _AppError
            from app.routers.public_pages import error_page

            error = _AppError(message)
            error.status_code = exc.status_code
            return await error_page(request, error)
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": message, "code": f"http_{exc.status_code}"},
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        logger.error(
            "Необработанное исключение на %s: %s",
            request.url.path,
            exc,
            exc_info=True,
        )
        message = "Произошла ошибка, мы уже знаем о ней"
        if _wants_html(request):
            from app.errors import AppError as _AppError
            from app.routers.public_pages import error_page

            return await error_page(request, _AppError(message))
        return JSONResponse(
            status_code=500, content={"detail": message, "code": "internal_error"}
        )


app = create_app()


@app.get("/health", tags=["Служебные"], summary="Проверка работоспособности")
def health() -> dict:
    return {"status": "ok", "app": settings.app_title, "env": settings.app_env}


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> RedirectResponse:
    return RedirectResponse(url="/static/img/mark.svg", status_code=307)


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
