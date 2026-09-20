"""Сканер QR: поиск заказа по коду и выдача (кухня и администратор сервиса)."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from tests.conftest import SUPER_PASSWORD, next_local_slot, order_payload

ROOT = Path(__file__).resolve().parent.parent


def _create(client: TestClient, establishment, menu, key: str) -> dict:
    response = client.post(
        "/api/orders",
        json=order_payload(establishment.id, [(menu[0].id, 1)], next_local_slot(), key=key),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_scan_requires_login(client: TestClient) -> None:
    assert client.get("/api/staff/orders/by-code/EX-ABCD").status_code == 401


def test_find_order_by_code_accepts_loose_input(client, staff_headers, establishment, menu) -> None:
    created = _create(client, establishment, menu, "scan-key-0001")
    code = created["order_code"]
    for variant in (code, code.lower(), code.replace("-", "")):
        response = client.get(f"/api/staff/orders/by-code/{variant}", headers=staff_headers)
        assert response.status_code == 200, response.text
        assert response.json()["order_code"] == code
        assert response.json()["items"]


def test_bad_code_is_rejected(client, staff_headers) -> None:
    response = client.get("/api/staff/orders/by-code/nonsense", headers=staff_headers)
    assert response.status_code == 400


def test_unknown_code_is_not_found(client, staff_headers) -> None:
    response = client.get("/api/staff/orders/by-code/EX-ZZZZ", headers=staff_headers)
    assert response.status_code in (400, 404)


def test_full_pickup_through_scanner(client, staff_headers, establishment, menu) -> None:
    code = _create(client, establishment, menu, "scan-key-0002")["order_code"]
    order = client.get(f"/api/staff/orders/by-code/{code}", headers=staff_headers).json()
    version = order["version"]
    for target in ("in_progress", "ready", "picked_up"):
        response = client.patch(
            f"/api/staff/orders/by-code/{code}/status",
            headers=staff_headers,
            json={"new_status": target, "version": version},
        )
        assert response.status_code == 200, response.text
        version = response.json()["version"]
    final = client.get(f"/api/staff/orders/by-code/{code}", headers=staff_headers).json()
    assert final["status"] == "picked_up"
    assert final["allowed_transitions"] == []


def test_super_admin_can_scan_any_order(client, super_admin, establishment, menu) -> None:
    code = _create(client, establishment, menu, "scan-key-0003")["order_code"]
    login = client.post(
        "/api/auth/login", json={"username": "superadmin", "password": SUPER_PASSWORD}
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    response = client.get(f"/api/staff/orders/by-code/{code}", headers=headers)
    assert response.status_code == 200
    assert response.json()["order_code"] == code


def test_scan_pages_render(client) -> None:
    order_page = client.get("/for-business")
    assert order_page.status_code == 200
    assert client.get("/static/js/qr.js").status_code == 200


def test_scan_page_serves_local_decoder(client, staff_headers) -> None:
    """Декодер едет со своего домена.

    Запасной декодер уже один раз пропал: ссылка на cdnjs отдавала 404,
    и сканер молча работал только там, где есть встроенный BarcodeDetector.
    """
    page = client.get("/scan")
    assert page.status_code == 200, page.text
    assert "/static/js/vendor/jsQR.min.js" in page.text, "страница не подключает свой декодер"
    assert "cdnjs" not in page.text, "декодер снова тянется со стороннего CDN"
    assert client.get("/static/js/vendor/jsQR.min.js").status_code == 200


def test_scan_page_has_fallbacks(client, staff_headers) -> None:
    """Если камеры нет или браузер её не пускает, остаются фото и ручной ввод."""
    page = client.get("/scan")
    assert page.status_code == 200, page.text
    assert 'id="scan-file"' in page.text and 'type="file"' in page.text, "нет загрузки фото QR"
    assert 'id="scan-input"' in page.text, "нет ручного ввода номера"


def test_qr_poster_is_drawn_locally(client, establishment) -> None:
    """Плакат рисует QR своим генератором: ни одного запроса на чужой домен."""
    page = client.get(f"/e/{establishment.id}/qr")
    assert page.status_code == 200, page.text
    assert "qrserver" not in page.text, "плакат снова зависит от стороннего сервиса"
    assert "data-qr=" in page.text, "на плакате нет места под QR"
    assert "/static/js/qr.js" in page.text, "генератор QR не подключён"


def test_no_external_scripts_or_images() -> None:
    """Скрипты и картинки — только со своего домена.

    Шрифты с Google Fonts оставлены осознанно: без них страница просто
    отрисуется системным шрифтом. Недоступный скрипт ломает функцию целиком —
    именно так сканер QR потерял декодер, когда cdnjs отдал 404.
    """
    offenders: list[str] = []
    for path in (ROOT / "app" / "templates").rglob("*.html"):
        for match in re.finditer(
            r'<(?:script|img)[^>]*\bsrc="(https?://[^"]+)"', path.read_text(encoding="utf-8")
        ):
            offenders.append(f"{path.name}: {match.group(1)}")
    assert not offenders, f"внешние скрипты и картинки: {offenders}"
