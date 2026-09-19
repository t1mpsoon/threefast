"""Тесты проверки версии схемы при старте (app/schema_guard.py).

Зачем это тестировать: если проверка молчит или врёт, разработчик снова
получит трудночитаемый `no such column` вместо понятной подсказки.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from app.schema_guard import (
    ROOT,
    check_schema,
    current_revision,
    database_path,
    migration_head,
    startup_hint,
)


def test_migration_head_is_the_latest_revision() -> None:
    """Головная ревизия — та, на которую никто не ссылается как на предыдущую."""
    head = migration_head()
    assert head == "0005_superadmin_no_place", f"неожиданная головная ревизия: {head}"

    # Проверяем на файлах: цепочка миграций должна быть линейной и полной.
    revisions = {}
    parents = set()
    for path in sorted((ROOT / "migrations" / "versions").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.startswith("revision:"):
                revisions[line.split('"')[1]] = path.name
            if line.startswith("down_revision") and '"' in line:
                parents.add(line.split('"')[1])
    assert set(revisions) - parents == {head}, "в проекте больше одной головной ревизии"


def test_database_path_resolves_relative_url() -> None:
    path = database_path("sqlite:///./data/express_pickup.db")
    assert path is not None and path.name == "express_pickup.db"
    # Для других СУБД проверка не делается: только SQLite.
    assert database_path("postgresql://localhost/db") is None


def test_current_revision_reads_sqlite(tmp_path: Path) -> None:
    """Версия читается обычным sqlite3 — даже если схема сломана."""
    db_file = tmp_path / "probe.db"
    connection = sqlite3.connect(db_file)
    connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32))")
    connection.execute("INSERT INTO alembic_version VALUES ('0001_initial_schema')")
    connection.commit()
    connection.close()

    version, has_table = current_revision(db_file)
    assert version == "0001_initial_schema"
    assert has_table is True


def test_missing_table_is_reported_as_empty(tmp_path: Path) -> None:
    """База без alembic_version — это «схема создана из моделей», а не «ок»."""
    db_file = tmp_path / "empty.db"
    connection = sqlite3.connect(db_file)
    connection.execute("CREATE TABLE orders (id INTEGER)")
    connection.commit()
    connection.close()

    report = check_schema(f"sqlite:///{db_file.as_posix()}")
    assert report.state == "empty"
    assert report.current is None
    assert "alembic_version" in report.message


def test_outdated_database_gets_actionable_hint(tmp_path: Path) -> None:
    """Отставшая база: состояние outdated и подсказка с командой."""
    db_file = tmp_path / "stale.db"
    connection = sqlite3.connect(db_file)
    connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32))")
    connection.execute("INSERT INTO alembic_version VALUES ('0002_showcase')")
    connection.commit()
    connection.close()

    url = f"sqlite:///{db_file.as_posix()}"
    report = check_schema(url)
    assert report.state == "outdated"
    assert report.current == "0002_showcase"
    assert report.head == "0005_superadmin_no_place"
    assert not report.is_ok

    hint = startup_hint(report, url)
    assert hint is not None
    assert "alembic upgrade head" in hint, "в подсказке должна быть готовая команда"
    assert "0002_showcase" in hint and "0005_superadmin_no_place" in hint


def test_current_database_has_no_hint() -> None:
    """На синхронной демо-базе проверка молчит и не пугает разработчика."""
    url = "sqlite:///./data/express_pickup.db"
    report = check_schema(url)
    # Демо-база должна быть на головной ревизии: иначе падает логин.
    assert report.state == "ok", report.message
    assert report.current == report.head
    assert startup_hint(report, url) is None


def test_real_demo_database_matches_models() -> None:
    """В демо-базе есть и orders.note, и staff_users.is_super."""
    db_file = database_path("sqlite:///./data/express_pickup.db")
    assert db_file is not None and db_file.exists()

    connection = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    try:
        columns = lambda table: {
            row[1] for row in connection.execute(f"PRAGMA table_info({table})")
        }
        assert "note" in columns("orders"), "миграция 0003_order_note не применена"
        assert "is_super" in columns("staff_users"), "миграция 0004_super_admin не применена"
    finally:
        connection.close()


def test_startup_guard_never_raises(tmp_path: Path, monkeypatch) -> None:
    """Проверка при старте не должна ронять приложение даже при ошибке."""
    from app import schema_guard

    def broken(_url: str):
        raise sqlite3.OperationalError("база недоступна")

    monkeypatch.setattr(schema_guard, "check_schema", broken)
    report = schema_guard.warn_if_outdated("sqlite:///./data/express_pickup.db")
    assert report.state == "unknown"
    assert "недоступна" in report.message
