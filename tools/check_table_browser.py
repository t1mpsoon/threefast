"""Проверка выбора заведения и столика в настоящих браузерах.

Что проверяем:
  1. на странице плаката можно выбрать другое заведение и конкретный столик,
     и после «Обновить» плакат действительно меняется;
  2. метка стола из ссылки (`?src=table7`) сама подставляется в поле «Столик»
     на оформлении заказа.

Запуск: python -m tools.check_table_browser [базовый_URL]
Требует playwright и запущенный сервер приложения.
"""

from __future__ import annotations

import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"

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


def run_engine(engine, title: str, places: list[dict]) -> None:
    print(f"\n── {title} ──")
    browser = engine.launch()
    page = browser.new_context(viewport={"width": 900, "height": 1000}).new_page()
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on(
        "console",
        lambda msg: errors.append(msg.text) if msg.type == "error" else None,
    )

    first, second = places[0], places[1]

    # ── Плакат: выбираем другое заведение и конкретный столик ──────────────
    page.goto(f"{BASE}/e/{first['id']}/qr", wait_until="domcontentloaded")
    # Имя на плакате набрано прописными (text-transform), поэтому сверяем без регистра.
    shown = page.locator(".qr-poster__name").inner_text().strip().casefold()
    check(f"{title}: плакат открылся для {first['name']}",
          first["name"].casefold() in shown, shown)

    options = page.locator('select[name="place"] option').all_inner_texts()
    check(f"{title}: в списке есть все заведения", len(options) == len(places), options)

    page.select_option('select[name="place"]', str(second["id"]))
    page.select_option('select[name="print"]', "table5")
    page.click('button[type="submit"]')
    # Форма уходит обычным GET: ждём именно новый адрес, иначе WebKit успевает
    # прочитать старый (переход ещё не случился).
    page.wait_for_url(f"**/e/{second['id']}/qr**", timeout=20_000)

    check(f"{title}: переключились на другое заведение",
          f"/e/{second['id']}/qr" in page.url, page.url)
    posters = page.locator(".qr-poster")
    check(f"{title}: на плакате ровно один столик", posters.count() == 1, posters.count())
    check(f"{title}: напечатан выбранный столик",
          "Стол 5" in page.locator(".qr-poster__table").inner_text(),
          page.locator(".qr-poster__table").inner_text())
    check(f"{title}: на плакате имя выбранного заведения",
          second["name"].casefold() in page.locator(".qr-poster__name").inner_text().casefold(),
          page.locator(".qr-poster__name").inner_text())

    # В адресе остался выбранный столик: ссылку можно сохранить и напечатать.
    check(f"{title}: адрес содержит выбранный столик", "table=5" in page.url, page.url)

    # ── Оформление: метка стола подставляется сама ─────────────────────────
    page.goto(f"{BASE}/e/{second['id']}/menu?src=table7", wait_until="domcontentloaded")
    field = page.locator("#guest-table")
    check(f"{title}: поле столика есть на оформлении", field.count() == 1)
    check(f"{title}: столик подставился из ссылки плаката",
          field.input_value() == "7", field.input_value())

    # Ссылка без метки не подставляет ничего.
    page.goto(f"{BASE}/e/{second['id']}/menu", wait_until="domcontentloaded")
    check(f"{title}: без метки поле пустое",
          page.locator("#guest-table").input_value() == "",
          page.locator("#guest-table").input_value())

    check(f"{title}: без ошибок в консоли", not errors, errors[:3])
    browser.close()


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:  # pragma: no cover
        print("нужен playwright: pip install playwright && playwright install chromium webkit")
        return 2

    with httpx.Client(base_url=BASE, timeout=60.0) as client:
        response = client.get("/api/establishments/home")
        if response.status_code != 200:
            print(f"витрина недоступна: {response.status_code}")
            return 2
        payload = response.json()
        places = payload.get("places") or payload
        if len(places) < 2:
            print("нужно хотя бы два заведения — проверку не запустить")
            return 2

        with sync_playwright() as p:
            run_engine(p.chromium, "chromium (Chrome/Edge)", places)
            run_engine(p.webkit, "webkit (движок Safari)", places)

    print(f"\nИТОГО проверок: {checks}, провалов: {len(failures)}")
    for item in failures:
        print("  ПРОВАЛ:", item)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
