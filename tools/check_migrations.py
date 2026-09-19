"""Служебная проверка: миграции Alembic дают ту же схему, что модели SQLAlchemy.

Запуск: python -m tools.check_migrations

Важно: скрипт удаляет только те ревизии, которые сам же и создал. Раньше он
удалял все файлы кроме 0001 и однажды снёс настоящую миграцию.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSIONS = ROOT / "migrations" / "versions"
TEMP_DB = Path(tempfile.gettempdir()) / "ep_alembic_check.db"


def run(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def known_revisions() -> set[str]:
    """Файлы ревизий, которые лежат в проекте до запуска проверки."""
    return {path.name for path in VERSIONS.glob("*.py")}


def main() -> int:
    if TEMP_DB.exists():
        TEMP_DB.unlink()

    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite:///{TEMP_DB.as_posix()}"
    env["SECRET_KEY"] = "alembic-check-secret"

    before = known_revisions()

    upgrade = run(["alembic", "upgrade", "head"], env)
    print("alembic upgrade head:", "OK" if upgrade.returncode == 0 else "FAIL")
    if upgrade.returncode != 0:
        print(upgrade.stdout[-2000:], upgrade.stderr[-2000:])
        return 1

    revision = run(["alembic", "revision", "--autogenerate", "-m", "drift"], env)
    if revision.returncode != 0:
        print("autogenerate не сработал:")
        print(revision.stdout[-2000:], revision.stderr[-2000:])
        return 1

    # Удаляем и разбираем только то, что появилось в этом запуске.
    created = [path for path in VERSIONS.glob("*.py") if path.name not in before]
    operations: list[str] = []
    for path in created:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(("op.", "batch_op.")):
                operations.append(line.strip())
        path.unlink()

    if operations:
        print("ОБНАРУЖЕН ДРЕЙФ СХЕМЫ (модели разошлись с миграциями):")
        for line in operations:
            print("  ", line)
        return 1

    print(f"ревизий в проекте: {len(before)}")
    print("Дрейфа схемы нет: миграции и модели совпадают")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
