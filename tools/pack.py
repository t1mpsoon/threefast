"""Сборка архива проекта для сдачи.

Запуск: python -m tools.pack

Собирает два архива в каталог dist/:
* ThreeFast-src.zip — только исходники: без базы, снимков и логов;
* ThreeFast-demo.zip — то же плюс база с демо-данными и снимки экранов,
  чтобы проверяющий увидел проект без долгой подготовки.

Виртуальное окружение, кеши и логи не попадают ни в один архив.
"""

from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

# Что не попадает в архив никогда.
SKIP_DIRS = {
    "venv", ".venv", "__pycache__", ".pytest_cache", ".git", ".idea", ".vscode",
    "dist", "node_modules", "logs",
}
SKIP_FILES = {"*.pyc", "*.pyo", "*.log", "*.db-shm", "*.db-wal", ".DS_Store"}

# Демо-версия дополнительно получает базу и готовую презентацию.
DEMO_ONLY = ("data", "presentation")

# Результаты прогонов: в архивах им не место. Снимки проверок — рабочий
# материал, их всегда можно снять заново; в поставку идёт только презентация,
# которую собирает tools.screenshots.
OUTPUT_DIRS = {"shots", "presentation"}


def should_skip(path: Path, *, demo: bool) -> bool:
    parts = set(path.relative_to(ROOT).parts)
    if parts & SKIP_DIRS:
        return True
    if path.suffix in {".pyc", ".pyo", ".log"}:
        return True
    if path.name in {"express_pickup.db-shm", "express_pickup.db-wal"}:
        return True
    if not demo:
        if parts & set(DEMO_ONLY):
            return True
        if path.suffix == ".db":
            return True
    return False


def is_output(path: Path, *, allow: set[str] | None = None) -> bool:
    """Результат прогона, а не исходник: снимки, архивы, выгрузки.

    `allow` оставляет нужный каталог: презентация — часть поставки, снимки
    проверок — нет.
    """
    parts = set(path.relative_to(ROOT).parts)
    blocked = OUTPUT_DIRS - (allow or set())
    return bool(parts & blocked)


def collect(*, demo: bool) -> list[Path]:
    # Демо-архив оставляет презентацию: она часть поставки.
    allow = {"presentation"} if demo else set()
    files: list[Path] = []
    for path in sorted(ROOT.rglob("*")):
        if path.is_dir():
            continue
        if path.is_symlink():
            continue
        relative = path.relative_to(ROOT)
        # Каталог dist и сам себя не пакуем.
        if relative.parts and relative.parts[0] in SKIP_DIRS:
            continue
        if is_output(path, allow=allow):
            continue
        if should_skip(path, demo=demo):
            continue
        files.append(path)
    return files


def build(*, demo: bool) -> Path:
    name = "ThreeFast-demo.zip" if demo else "ThreeFast-src.zip"
    target = DIST / name
    files = collect(demo=demo)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.write(path, Path("ThreeFast") / path.relative_to(ROOT))
    return target


def main() -> int:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)

    clean = build(demo=False)
    full = build(demo=True)

    print("=== архивы ===")
    for archive in (clean, full):
        size = archive.stat().st_size / 1024 / 1024
        with zipfile.ZipFile(archive) as opened:
            count = len(opened.namelist())
        print(f"  {archive.name}: {count} файлов, {size:.1f} МБ")

    # Проверяем, что в исходный архив не просочились база и снимки.
    with zipfile.ZipFile(clean) as opened:
        names = opened.namelist()
    leaks = [n for n in names
         if n.endswith(".db") or "/venv/" in n or "__pycache__" in n or n.endswith(".log")
         or n.startswith("ThreeFast/shots/") or n.startswith("ThreeFast/presentation/")]
    print("\n=== проверка чистоты исходного архива ===")
    print("  лишнего:", leaks or "нет")
    return 1 if leaks else 0


if __name__ == "__main__":
    raise SystemExit(main())
