"""Проверка сканера QR в настоящих браузерах: Chromium и WebKit (движок Safari).

Камера не нужна. Chromium получает поддельную камеру, в которую записан
сгенерированный QR-код (`--use-file-for-fake-video-capture`), а путь «загрузить
фото» проверяется обычной картинкой PNG. Так видно то, чего не видно в
модульных тестах: браузер действительно распознал код и открыл карточку заказа.

Запуск: python -m tools.check_scan_browser [базовый_URL] [логин] [пароль]
Требует playwright и запущенный сервер приложения.
"""

from __future__ import annotations

import struct
import sys
import tempfile
import time
import zlib
from datetime import datetime, timedelta
from pathlib import Path

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
USERNAME = sys.argv[2] if len(sys.argv) > 2 else "staff"
PASSWORD = sys.argv[3] if len(sys.argv) > 3 else "staff-pass-123"

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="scan-check-"))
QUIET = 4  # поле вокруг кода: без него камера не находит «глаза» QR

failures: list[str] = []
checks = 0


def check(label: str, condition: bool, extra: object = "") -> None:
    global checks
    checks += 1
    if condition:
        print(f"[OK  ] {label}")
    else:
        failures.append(label)
        print(f"[FAIL] {label}  -> {extra}")


# ── Картинка из матрицы QR ──────────────────────────────────────────────────
def rasterize(matrix: list[list[bool]], side: int) -> tuple[int, int, list[bytes]]:
    """Матрица модулей -> строки RGB заданной высоты (код по центру, поле 4 модуля)."""
    modules = len(matrix) + QUIET * 2
    scale = max(1, side // modules)
    qr_side = modules * scale
    width = height = side
    offset = (side - qr_side) // 2

    rows: list[bytes] = []
    for y in range(height):
        row = bytearray(b"\xff" * (width * 3))
        qy = (y - offset) // scale - QUIET
        if 0 <= qy < len(matrix):
            for x in range(width):
                qx = (x - offset) // scale - QUIET
                if 0 <= qx < len(matrix) and matrix[qy][qx]:
                    row[x * 3] = row[x * 3 + 1] = row[x * 3 + 2] = 0
        rows.append(bytes(row))
    return width, height, rows


def write_png(path: Path, width: int, height: int, rows: list[bytes]) -> None:
    """Минимальный PNG без внешних библиотек: zlib есть в стандартной поставке."""
    raw = b"".join(b"\x00" + row for row in rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)


def write_y4m(path: Path, width: int, height: int, rows: list[bytes], frames: int = 40) -> None:
    """Видео для поддельной камеры Chromium: YUV420p, несколько одинаковых кадров."""
    y_plane = bytearray()
    u_plane = bytearray()
    v_plane = bytearray()
    for y in range(height):
        row = rows[y]
        for x in range(width):
            r, g, b = row[x * 3], row[x * 3 + 1], row[x * 3 + 2]
            y_plane.append(max(0, min(255, int(0.299 * r + 0.587 * g + 0.114 * b))))
            if y % 2 == 0 and x % 2 == 0:
                u_plane.append(max(0, min(255, int(-0.169 * r - 0.331 * g + 0.5 * b + 128))))
                v_plane.append(max(0, min(255, int(0.5 * r - 0.419 * g - 0.081 * b + 128))))
    frame = bytes(y_plane + u_plane + v_plane)
    with path.open("wb") as handle:
        handle.write(f"YUV4MPEG2 W{width} H{height} F25:1 Ip A1:1 C420mpeg2\n".encode())
        for _ in range(frames):
            handle.write(b"FRAME\n")
            handle.write(frame)


# ── Данные для проверки ─────────────────────────────────────────────────────
def create_order(client: httpx.Client) -> tuple[str, str]:
    """Заводит заказ и возвращает (код, текст для QR).

    Слот берём на завтра: у сегодняшних есть минимальный запас по времени
    приготовления, и ранним утром свободных слотов может не остаться.
    """
    menu = client.get("/api/establishments/1/menu").json()["items"]
    tomorrow = (datetime.now() + timedelta(days=1)).date().isoformat()
    slots = client.get(f"/api/establishments/1/slots?date={tomorrow}").json()["slots"]
    free = [s for s in slots if s["available"]]
    if not free:
        raise RuntimeError("нет свободных слотов — проверку не запустить")
    payload = {
        "establishment_id": 1,
        "slot_datetime": free[0]["slot_datetime"],
        "guest_name": "Проверка Сканера",
        "guest_phone": "8 701 000 11 22",
        "items": [{"menu_item_id": menu[0]["id"], "quantity": 1}],
        "payment_method": "cash_on_pickup",
        "idempotency_key": f"scan-browser-{int(time.time())}",
    }
    response = client.post("/api/orders", json=payload)
    if response.status_code != 201:
        raise RuntimeError(f"заказ не создан: {response.status_code} {response.text[:300]}")
    order = response.json()
    return order["order_code"], order["order_code"]


def staff_cookie(client: httpx.Client) -> str:
    login = client.post("/api/auth/login", json={"username": USERNAME, "password": PASSWORD})
    if login.status_code != 200:
        raise RuntimeError(f"вход {USERNAME!r} не удался: {login.status_code} {login.text[:200]}")
    return login.json()["access_token"]


def scan_with_photo(page, context, code: str, png: Path) -> None:
    page.goto(f"{BASE}/scan", wait_until="domcontentloaded")
    check("страница сканера открыта", page.locator("#scan-form").count() == 1, page.url)
    page.set_input_files("#scan-file", str(png))
    _expect_order_card(page, code, "фото QR")


def scan_with_camera(page, context, code: str) -> None:
    page.goto(f"{BASE}/scan", wait_until="domcontentloaded")
    # Камера поднимается сама при открытии страницы. Если браузер ждёт касания
    # (так делает iOS), кнопка останется в положении «Включить камеру».
    page.wait_for_timeout(2000)
    toggle = page.locator("#scan-toggle")
    if toggle.count() and toggle.inner_text().strip().startswith("Включить"):
        toggle.click()
    _expect_order_card(page, code, "камера")


def _expect_order_card(page, code: str, label: str) -> None:
    try:
        page.wait_for_selector(".scan-card", timeout=25_000)
    except Exception:
        hint = page.locator("#scan-hint").inner_text() if page.locator("#scan-hint").count() else ""
        check(f"{label}: карточка заказа открылась", False, f"подсказка: {hint!r}")
        return
    text = page.locator(".scan-card").inner_text()
    check(f"{label}: карточка заказа открылась", code in text, text[:200])
    check(
        f"{label}: есть кнопка выдачи",
        page.locator(".scan-card [data-advance]").count() == 1,
        text[:200],
    )


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:  # pragma: no cover
        print("нужен playwright: pip install playwright && playwright install chromium webkit")
        return 2

    with httpx.Client(base_url=BASE, timeout=60.0) as client:
        code, qr_text = create_order(client)
        token = staff_cookie(client)
    print(f"заказ для проверки: {code}")

    with sync_playwright() as p:
        # Матрицу QR считает тот же генератор, что и в приложении.
        generator = p.chromium.launch()
        page = generator.new_page()
        page.goto(f"{BASE}/", wait_until="domcontentloaded")
        page.add_script_tag(path=str(ROOT / "app" / "static" / "js" / "qr.js"))
        matrix = page.evaluate("(text) => EPQR.matrix(text)", qr_text)
        generator.close()

        width, height, rows = rasterize(matrix, 480)
        png = TMP / "order-qr.png"
        write_png(png, width, height, rows)
        y4m = TMP / "order-qr.y4m"
        write_y4m(y4m, width, height, rows)
        print(f"QR версии {len(matrix)}x{len(matrix)}: {png.name}, {y4m.name}")

        engines = [
            ("chromium (Chrome/Edge)", p.chromium, True),
            ("webkit (движок Safari)", p.webkit, False),
        ]
        for title, engine, fake_camera in engines:
            args = (
                [
                    "--use-fake-ui-for-media-stream",
                    "--use-fake-device-for-media-stream",
                    f"--use-file-for-fake-video-capture={y4m}",
                ]
                if fake_camera
                else []
            )
            browser = engine.launch(args=args)
            context = browser.new_context(viewport={"width": 420, "height": 900})
            context.add_cookies([{"name": "ep_token", "value": token, "url": BASE}])
            page = context.new_page()
            errors: list[str] = []

            def note_error(message: str) -> None:
                # Вибрация требует касания экрана: браузер сообщает об этом
                # ошибкой в консоли, хотя это не дефект, а политика движка.
                if "navigator.vibrate" in message:
                    return
                errors.append(message)

            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.on(
                "console",
                lambda msg: note_error(msg.text) if msg.type == "error" else None,
            )

            print(f"\n── {title} ──")
            scan_with_photo(page, context, code, png)
            if fake_camera:
                scan_with_camera(page, context, code)

            check(f"{title}: без ошибок в консоли", not errors, errors[:3])
            browser.close()

    print(f"\nИТОГО проверок: {checks}, провалов: {len(failures)}")
    for item in failures:
        print("  ПРОВАЛ:", item)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
