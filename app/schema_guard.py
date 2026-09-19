"""Проверка версии схемы при старте приложения.

Зачем: если демо-база отстала от миграций, приложение поднимается, а падает
позже — на первом же запросе к новой колонке, с трудночитаемым
`OperationalError: no such column`. Гость видит 500, разработчик ищет причину.

Здесь мы до начала работы сравниваем версию в `alembic_version` с головной
ревизией проекта и печатаем понятную инструкцию. Проверка ничего не меняет:
миграции применяет `alembic upgrade head`, чтобы не было неожиданных правок
чужой базы.

Модуль намеренно не тянет SQLAlchemy и модели: он должен работать даже тогда,
когда схема сломана настолько, что ORM не поднимается.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.logging_utils import get_logger

# Логгер проекта: сообщения попадают и в консоль, и в logs/app.log.
logger = get_logger("schema_guard")


ROOT = Path(__file__).resolve().parent.parent
VERSIONS = ROOT / "migrations" / "versions"

_REVISION = re.compile(r'^revision:\s*str\s*=\s*["\']([^"\']+)["\']', re.M)
_DOWN = re.compile(r'^down_revision[^=]*=\s*(?:"([^"]+)"|\'([^\']+)\'|None)', re.M)


@dataclass
class SchemaReport:
    """Результат проверки: state — ok | outdated | empty | unknown."""

    state: str
    current: str | None
    head: str | None
    message: str

    @property
    def is_ok(self) -> bool:
        return self.state == "ok"

    def __str__(self) -> str:  # pragma: no cover — для логов
        return f"[{self.state}] {self.message}"


def migration_head(versions: Path | None = None) -> str | None:
    """Головная ревизия: та, на которую не ссылается ни один down_revision."""
    folder = versions or VERSIONS
    revisions: dict[str, str | None] = {}
    for path in sorted(folder.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        revision = _REVISION.search(text)
        if not revision:
            continue
        down = _DOWN.search(text)
        parent = None
        if down:
            parent = down.group(1) or down.group(2)
        revisions[revision.group(1)] = parent

    if not revisions:
        return None
    parents = {value for value in revisions.values() if value}
    heads = [name for name in revisions if name not in parents]
    # Если голов несколько (разошлись ветки) — берём первую по алфавиту:
    # приложение всё равно сообщит о расхождении.
    return sorted(heads)[0] if heads else None


def database_path(database_url: str) -> Path | None:
    """Путь к файлу SQLite. Для других СУБД проверка не делается."""
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return None
    raw = database_url[len(prefix):]
    path = Path(raw)
    if not path.is_absolute():
        path = (ROOT / raw).resolve()
    return path


def current_revision(db_file: Path) -> tuple[str | None, bool]:
    """(версия в базе, есть ли таблица alembic_version).

    Читаем обычным sqlite3: проверка должна работать и на битой схеме.
    """
    if not db_file.exists():
        return None, False
    try:
        connection = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    except sqlite3.Error:
        return None, False
    try:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        ).fetchone()
        if not table:
            return None, False
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        return (row[0] if row else None), True
    except sqlite3.Error:
        return None, False
    finally:
        connection.close()


def check_schema(database_url: str, *, versions: Path | None = None) -> SchemaReport:
    """Сравнивает версию демо-базы с последней миграцией проекта."""
    head = migration_head(versions)
    if head is None:
        return SchemaReport("unknown", None, None,
                            "в проекте не найдено ни одной миграции")

    db_file = database_path(database_url)
    if db_file is None:
        return SchemaReport("unknown", None, head,
                            "проверка версии поддерживается только для SQLite")

    current, has_table = current_revision(db_file)
    if not has_table:
        return SchemaReport(
            "empty", current, head,
            f"в базе {db_file.name} нет таблицы alembic_version: схема создана "
            f"напрямую из моделей. Для чистой базы примените миграции.",
        )
    if current == head:
        return SchemaReport("ok", current, head,
                            f"схема соответствует миграциям (ревизия {current})")
    return SchemaReport(
        "outdated", current, head,
        f"база на ревизии {current or '—'}, а проект ждёт {head}",
    )


def startup_hint(report: SchemaReport, database_url: str) -> str | None:
    """Готовая подсказка для консоли. None — если всё в порядке."""
    if report.is_ok:
        return None

    db_file = database_path(database_url)
    where = str(db_file) if db_file else database_url
    if report.state == "outdated":
        return (
            "\n" + "=" * 70 + "\n"
            "  ВНИМАНИЕ: база данных отстала от миграций\n"
            + "=" * 70 + "\n"
            f"  База:    {where}\n"
            f"  Сейчас:  {report.current or '—'}\n"
            f"  Нужно:   {report.head}\n\n"
            "  Что делать:\n"
            "    python -m alembic upgrade head\n\n"
            "  Без этого части приложения упадут с ошибкой вида\n"
            "  «no such column», потому что модели ждут новых полей.\n"
            + "=" * 70
        )
    if report.state == "empty":
        return (
            "\n" + "=" * 70 + "\n"
            "  ВНИМАНИЕ: база данных создана без миграций\n"
            + "=" * 70 + "\n"
            f"  База: {where}\n\n"
            "  Таблицы есть, но версия схемы не отмечена. Если база пустая:\n"
            "    python -m alembic upgrade head\n"
            "  Если это тестовая база, созданная из моделей, — всё в порядке.\n"
            + "=" * 70
        )
    return None


def warn_if_outdated(database_url: str) -> SchemaReport:
    """Проверка для события старта: сообщает о расхождении, но не мешает работе.

    Пишем на уровне WARNING даже про успех: так строку видно при любом
    LOG_LEVEL и не приходится гадать, выполнялась проверка или нет.
    """
    try:
        report = check_schema(database_url)
    except Exception as error:  # pragma: no cover — проверка не должна ронять старт
        logger.warning("Не удалось проверить версию схемы: %s", error)
        return SchemaReport("unknown", None, None, str(error))

    if report.is_ok:
        logger.warning("Схема БД: %s", report.message)
        return report

    hint = startup_hint(report, database_url)
    if hint:
        logger.warning(hint)
    return report
