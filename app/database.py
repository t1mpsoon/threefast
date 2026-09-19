"""Инициализация SQLAlchemy: engine, фабрика сессий, Base, UTC-тип (раздел 3.1 ТЗ)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, Engine, TypeDecorator, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import BASE_DIR, settings


class Base(DeclarativeBase):
    """Базовый класс декларативных моделей."""


class UTCDateTime(TypeDecorator):
    """DATETIME, который всегда хранится в UTC.

    SQLite не хранит информацию о таймзоне, поэтому:
    * при записи наивное значение трактуется как UTC;
    * при чтении к значению возвращается tzinfo=UTC,
      чтобы `datetime.now(timezone.utc) - row.created_at` работало корректно.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).astimezone(timezone.utc).replace(tzinfo=None)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def _ensure_sqlite_directory(url: str) -> None:
    """Создаёт папку data/ до открытия файла БД, иначе SQLite не стартует."""
    prefix = "sqlite:///"
    if not url.startswith(prefix) or ":memory:" in url:
        return
    raw_path = url[len(prefix) :]
    if raw_path.startswith("/") and len(raw_path) > 2 and raw_path[2] == ":":
        raw_path = raw_path[1:]  # sqlite:///C:/... -> C:/...
    db_path = Path(raw_path)
    target = db_path if db_path.is_absolute() else (BASE_DIR / db_path)
    target.parent.mkdir(parents=True, exist_ok=True)


def build_engine(database_url: str | None = None) -> Engine:
    """Создаёт Engine с параметрами, корректными для SQLite и для тестов in-memory."""
    url = database_url or settings.database_url
    kwargs: dict[str, Any] = {"future": True}

    if url.startswith("sqlite"):
        _ensure_sqlite_directory(url)
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            # Один общий коннект: иначе каждая сессия получила бы свою пустую БД.
            kwargs["poolclass"] = StaticPool
        else:
            # WAL повышает устойчивость к конкурентным чтениям/записям (защита от "database is locked").
            kwargs["connect_args"]["timeout"] = 30
    else:
        # Managed-базы на хостинге закрывают простаивающие соединения: без
        # проверки живости первый запрос после паузы падает с «server closed
        # the connection unexpectedly».
        kwargs["pool_pre_ping"] = True
        kwargs["pool_recycle"] = 280

    engine = create_engine(url, **kwargs)

    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            # FK constraints — предотвращают orphan order_items (раздел 2.11 ТЗ).
            cursor.execute("PRAGMA foreign_keys=ON")
            if ":memory:" not in url:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    return engine


engine: Engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def get_db() -> Iterator[Session]:
    """FastAPI-зависимость: сессия на запрос с гарантированным закрытием."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope(factory: sessionmaker[Session] = SessionLocal) -> Iterator[Session]:
    """Транзакционный контекст для скриптов и фоновых задач."""
    db = factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
