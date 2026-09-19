"""Проверка импортов и запуск приложения без ошибок (быстрый smoke-тест)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    from app.main import app  # noqa: F401

    routes = sorted(
        (getattr(route, "path", "?"), ",".join(sorted(getattr(route, "methods", []) or [])))
        for route in app.routes
    )
    print(f"OK: приложение собрано, маршрутов — {len(routes)}")
    for path, methods in routes:
        if path.startswith(("/api", "/e/", "/staff", "/admin", "/login", "/order", "/health")):
            print(f"  {methods or '-':<12} {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
