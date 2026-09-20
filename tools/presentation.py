"""Сборка презентации проекта: картинки для слайдов и QR на живой сайт.

Запуск: python -m tools.presentation

Что делает:
1. уменьшает снимки из presentation/ до ширины слайда (иначе колода весит
   десятки мегабайт и медленно открывается);
2. рисует QR-код со ссылкой на развёрнутый сайт — тем же генератором,
   что и в приложении (app/static/js/qr.js), через Node;
3. складывает всё в presentation/deck/.

Сборка PDF — отдельно: python -m tools.presentation --pdf
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "presentation"
DECK = SOURCE / "deck"
IMAGES = DECK / "img"

# Ширина под 2x-кадр на слайде: больше не нужно, слайд 1280 px.
MAX_WIDTH = 1600
QUALITY = 86

SITE = "https://threefast.onrender.com"

# Какие снимки нужны колоде: имя файла -> короткое имя для вставки.
WANTED = {
    "01-guest-home": "home",
    "03-guest-menu": "menu",
    "06-sheet-time": "time",
    "07-sheet-checkout": "checkout",
    "09-order-success": "success",
    "10-kitchen-queue": "kitchen",
    "13-admin-analytics": "analytics",
    "14-super-places": "platform",
    "16-dark-home": "dark",
    "19-mobile-menu": "menuphone",
    "20-mobile-sheet": "timephone",
    "20b-mobile-checkout": "checkoutphone",
    "22-scan-page": "scan",
    "23-scan-card": "scancard",
    "24-order-live": "live",
    "25-order-cancelled": "cancelled",
    "26-qr-poster": "poster",
}


# Фотографии демо-заведений: нужны на слайде про аудиторию.
PLACES = {
    "central": "place-central",
    "green": "place-green",
    "cup": "place-cup",
}


def shrink() -> int:
    """Уменьшает снимки до ширины слайда. Без Pillow — копирует как есть."""
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover — сборка не должна падать из-за этого
        print("Pillow не установлен: копирую снимки без уменьшения")
        IMAGES.mkdir(parents=True, exist_ok=True)
        made = 0
        for name, short in WANTED.items():
            source = SOURCE / f"{name}.png"
            if source.exists():
                shutil.copyfile(source, IMAGES / f"{short}.png")
                made += 1
        return made

    IMAGES.mkdir(parents=True, exist_ok=True)
    made = 0
    for name, short in WANTED.items():
        source = SOURCE / f"{name}.png"
        if not source.exists():
            print(f"  нет кадра {name}.png — пропускаю")
            continue
        with Image.open(source) as image:
            image = image.convert("RGB")
            if image.width > MAX_WIDTH:
                height = round(image.height * MAX_WIDTH / image.width)
                image = image.resize((MAX_WIDTH, height), Image.LANCZOS)
            target = IMAGES / f"{short}.jpg"
            image.save(target, "JPEG", quality=QUALITY, optimize=True, progressive=True)
        made += 1
        size = (IMAGES / f"{short}.jpg").stat().st_size / 1024
        print(f"  {short}.jpg  {size:,.0f} КБ")
    return made


def place_photos() -> int:
    """Фото заведений из приложения — чтобы слайд про аудиторию был живым."""
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover
        return 0

    source_dir = ROOT / "app" / "static" / "img" / "places"
    IMAGES.mkdir(parents=True, exist_ok=True)
    made = 0
    for name, short in PLACES.items():
        source = source_dir / f"{name}.jpg"
        if not source.exists():
            continue
        with Image.open(source) as image:
            image = image.convert("RGB")
            if image.width > 900:
                image = image.resize(
                    (900, round(image.height * 900 / image.width)), Image.LANCZOS
                )
            image.save(IMAGES / f"{short}.jpg", "JPEG", quality=86, optimize=True)
        made += 1
        print(f"  {short}.jpg")
    return made


def make_qr() -> bool:
    """QR на живой сайт: генератор тот же, что в приложении."""
    node = shutil.which("node")
    if node is None:
        print("Node не найден — QR на последний слайд не попадёт")
        return False

    # Значения подставляем прямо в скрипт: у `node -e` своя нумерация argv,
    # и передавать их аргументами — источник путаницы.
    script = f"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = {json.dumps(str(ROOT))}, URL_TEXT = {json.dumps(SITE)};
const sandbox = {{ window: {{}}, console }};
sandbox.window.window = sandbox.window;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(ROOT, 'app', 'static', 'js', 'qr.js'), 'utf8'), sandbox);
const svg = sandbox.window.EPQR.svg(URL_TEXT, {{ size: 320, label: 'Ссылка на ThreeFast' }});
// Размер задаёт вёрстка слайда, поэтому в самом SVG он относительный.
fs.writeFileSync(
  path.join(ROOT, 'presentation', 'deck', 'qr.svg'),
  svg.replace('width="320"', 'width="100%"').replace('height="320"', 'height="100%"')
);
console.log('qr ok');
"""
    DECK.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [node, "-e", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        print("QR не собрался:", result.stderr[-400:])
        return False
    print(f"  qr.svg  ({SITE})")
    return True


def export_pdf() -> bool:
    """Печатает колоду в PDF: один слайд — одна страница 16:9.

    Каждый слайд снимается картинкой и складывается в страницу. Векторный
    текст в PDF не переносится, зато разбиение на страницы не зависит от
    пагинации Chrome: она добавляла пустые страницы на стыках, потому что
    документ выходил на 17 px выше слайда из-за строчных боксов в разметке.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:  # pragma: no cover
        print("нужен playwright: pip install playwright && playwright install chromium")
        return False

    deck = DECK / "threefast.html"
    if not deck.exists():
        print(f"нет колоды {deck}")
        return False

    target = SOURCE / "threefast.pdf"
    with tempfile.TemporaryDirectory(prefix="threefast-pdf-") as folder:
        work = Path(folder)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 720},
                                    device_scale_factor=2)
            page.goto(deck.as_uri(), wait_until="networkidle")
            page.evaluate("() => document.fonts && document.fonts.ready")
            page.wait_for_timeout(1400)

            total = page.evaluate("() => document.querySelectorAll('.slide').length")
            pages: list[str] = []
            for number in range(1, total + 1):
                page.evaluate(
                    "(n) => document.querySelectorAll('.slide').forEach("
                    "(slide, i) => slide.classList.toggle('is-active', i === n - 1))",
                    number,
                )
                page.wait_for_timeout(180)
                shot = work / f"slide-{number:02d}.png"
                page.locator(".slide.is-active").screenshot(path=str(shot))
                pages.append(shot.as_uri())

            # Собираем страницы: картинка ровно по размеру страницы 16:9.
            builder = work / "builder.html"
            slides_html = "\n".join(
                f'<section><img src="{uri}" alt=""></section>' for uri in pages
            )
            builder.write_text(
                "<!DOCTYPE html><meta charset='utf-8'><style>"
                "@page{size:13.333in 7.5in;margin:0}"
                "html,body{margin:0;padding:0}"
                "section{width:1280px;height:720px;overflow:hidden;break-after:page;"
                "page-break-after:always}"
                "section:last-child{break-after:auto;page-break-after:auto}"
                "img{display:block;width:1280px;height:720px}"
                "</style>" + slides_html,
                encoding="utf-8",
            )
            sheet = browser.new_page(viewport={"width": 1280, "height": 720})
            sheet.goto(builder.as_uri(), wait_until="load")
            sheet.wait_for_timeout(400)
            sheet.pdf(
                path=str(target),
                width="13.333in",   # ровно 1280×720: картинка ложится страница в страницу
                height="7.5in",
                print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
            browser.close()

    size = target.stat().st_size / 1024 / 1024
    print(f"  threefast.pdf  {total} страниц, {size:.1f} МБ")
    return True


def write_guide() -> None:
    """Инструкция к колоде: кто что говорит и как её показывать."""
    lines = [
        "# ThreeFast — презентация защиты",
        "",
        "Открыть колоду: **`deck/threefast.html`** (двойной щелчок — откроется в браузере).",
        "Готовый PDF для отправки: **`threefast.pdf`** — 14 страниц 16:9, по слайду на страницу.",
        "",
        "PDF собран из изображений слайдов: так разбиение на страницы гарантированно",
        "совпадает со слайдами. Текст в нём не выделяется — если нужен PDF с текстом,",
        "откройте колоду в браузере и нажмите `Ctrl+P` → «Сохранить как PDF».",
        "",
        "## Управление",
        "",
        "| Клавиша | Что делает |",
        "|---|---|",
        "| `→` `Space` `PgDn` | следующий слайд |",
        "| `←` `PgUp` | предыдущий слайд |",
        "| `Home` / `End` | первый / последний слайд |",
        "| `F` | во весь экран |",
        "| `Ctrl+P` | печать в PDF |",
        "",
        "Клик по левой трети экрана листает назад, по остальному — вперёд.",
        "",
        "## Кто что говорит (5 минут, 4 спикера)",
        "",
        "| Спикер | Слайды | Блок |",
        "|---|---|---|",
        "| 1 | 1–4 | проблема и решение, целевая аудитория |",
        "| 2 | 5–9 | продукт: три шага, кухня, выдача, слежение, роли |",
        "| 3 | 10–11 | конкуренты и преимущества, расходы |",
        "| 4 | 12–14 | модель дохода, масштабируемость, финал |",
        "",
        "## Собрать заново",
        "",
        "```powershell",
        "python -m tools.screenshots          # свежие снимки приложения (нужен запущенный сервер)",
        "python -m tools.presentation         # картинки слайдов и QR на живой сайт",
        "python -m tools.presentation --pdf   # ещё и PDF",
        "```",
        "",
        "Снимки делаются с работающего приложения, поэтому колода всегда показывает",
        "то, что есть в коде, а не нарисованные макеты. Кадры лежат в `deck/img/`.",
    ]
    (DECK / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print("  deck/README.md")


def main() -> int:
    print("картинки:")
    made = shrink()
    print("фото заведений:")
    places = place_photos()
    print("QR:")
    has_qr = make_qr()
    write_guide()

    manifest = {
        "slides_images": made,
        "place_photos": places,
        "qr": has_qr,
        "site": SITE,
        "files": sorted(path.name for path in DECK.rglob("*") if path.is_file()),
    }
    (DECK / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if "--pdf" in sys.argv:
        print("PDF:")
        export_pdf()
    print(f"\nготово: колода в {DECK}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
