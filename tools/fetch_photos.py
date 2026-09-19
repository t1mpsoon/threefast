"""Скачивание фотографий для карточек блюд и заведений.

Запуск: python -m tools.fetch_photos [--force]

Складывает файлы в app/static/img/menu и app/static/img/places, чтобы демонстрация
работала без интернета. Источники — Unsplash (свободная лицензия), ссылки ниже;
для реального заведения их нужно заменить на фотографии своих блюд.
"""

from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MENU_DIR = ROOT / "app" / "static" / "img" / "menu"
PLACE_DIR = ROOT / "app" / "static" / "img" / "places"

# Фотографии с Unsplash: свободная лицензия, без обязательной атрибуции
# в интерфейсе, но источник указан в README.
MENU_PHOTOS = {
    "plov": "https://images.unsplash.com/photo-1512058564366-18510be2db19?w=480&h=360&fit=crop&q=70",
    "soup": "https://images.unsplash.com/photo-1547592166-23ac45744acd?w=480&h=360&fit=crop&q=70",
    "borsch": "https://images.unsplash.com/photo-1476718406336-bb5a9690ee2a?w=480&h=360&fit=crop&q=70",
    "caesar": "https://images.unsplash.com/photo-1550304943-4f24f54ddde9?w=480&h=360&fit=crop&q=70",
    "turkey": "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=480&h=360&fit=crop&q=70",
    "samsa": "https://images.unsplash.com/photo-1601050690597-df0568f70950?w=480&h=360&fit=crop&q=70",
    "baursak": "https://images.unsplash.com/photo-1509440159596-0249088772ff?w=480&h=360&fit=crop&q=70",
    "tea": "https://images.unsplash.com/photo-1544787219-7f47ccb76574?w=480&h=360&fit=crop&q=70",
    "compote": "https://images.unsplash.com/photo-1497534446932-c925b458314e?w=480&h=360&fit=crop&q=70",
    "cheesecake": "https://images.unsplash.com/photo-1533134242443-d4fd215305ad?w=480&h=360&fit=crop&q=70",
    "icecream": "https://images.unsplash.com/photo-1497034825429-c343d7c6a68f?w=480&h=360&fit=crop&q=70",
}

PLACE_PHOTOS = {
    "central": "https://images.unsplash.com/photo-1554118811-1e0d58224f24?w=900&h=520&fit=crop&q=70",
    "green": "https://images.unsplash.com/photo-1552566626-52f8b828add9?w=900&h=520&fit=crop&q=70",
    "cup": "https://images.unsplash.com/photo-1501339847302-ac426a4a7cbb?w=900&h=520&fit=crop&q=70",
}


def fetch(url: str, target: Path, force: bool = False) -> str:
    if target.exists() and not force:
        return f"есть   {target.name} ({target.stat().st_size // 1024} КБ)"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; ExpressPickUp/1.0)"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return f"ОШИБКА {target.name}: {error}"
    if len(payload) < 2000:
        return f"ОШИБКА {target.name}: слишком маленький файл ({len(payload)} байт)"
    target.write_bytes(payload)
    return f"скачал {target.name} ({len(payload) // 1024} КБ)"


def main() -> int:
    force = "--force" in sys.argv
    MENU_DIR.mkdir(parents=True, exist_ok=True)
    PLACE_DIR.mkdir(parents=True, exist_ok=True)

    failures = 0
    for slug, url in MENU_PHOTOS.items():
        line = fetch(url, MENU_DIR / f"{slug}.jpg", force)
        print(" ", line)
        failures += line.startswith("ОШИБКА")
        time.sleep(0.2)
    for slug, url in PLACE_PHOTOS.items():
        line = fetch(url, PLACE_DIR / f"{slug}.jpg", force)
        print(" ", line)
        failures += line.startswith("ОШИБКА")
        time.sleep(0.2)

    total = sum(f.stat().st_size for f in list(MENU_DIR.glob("*.jpg")) + list(PLACE_DIR.glob("*.jpg")))
    print(f"\nитого: {len(list(MENU_DIR.glob('*.jpg')))} фото блюд, "
          f"{len(list(PLACE_DIR.glob('*.jpg')))} фото заведений, {total // 1024} КБ")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
