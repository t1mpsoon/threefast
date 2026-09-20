"""Сессия смены и навигация по панелям.

Проверки появились после двух жалоб: планшет на кухне просил логин каждую
смену, а из панели было легко уехать вглубь — на телефоне ссылки в шапке
вообще скрывались, и вернуться к работе было нечем.
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.config import settings
from tests.conftest import STAFF_PASSWORD, SUPER_PASSWORD


def _login(client: TestClient, username: str, password: str, **extra) -> dict:
    response = client.post(
        "/api/auth/login", json={"username": username, "password": password, **extra}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _cookie_max_age(response) -> int:
    header = response.headers.get("set-cookie", "")
    match = re.search(r"max-age=(\d+)", header, re.I)
    assert match, f"в cookie нет срока жизни: {header}"
    return int(match.group(1))


# ── Сессия ──────────────────────────────────────────────────────────────────

def test_login_page_offers_remember_me(client) -> None:
    """На входе есть галочка «запомнить меня» и понятное объяснение."""
    page = client.get("/login")
    assert page.status_code == 200
    assert 'id="remember"' in page.text
    assert "Запомнить меня" in page.text
    assert str(settings.jwt_remember_days) in page.text


def test_remember_me_extends_cookie(client, users) -> None:
    """С галочкой сессия живёт недели, а не часы: смена не логинится каждый день."""
    response = client.post(
        "/api/auth/login",
        json={"username": "staff", "password": STAFF_PASSWORD, "remember": True},
    )
    assert response.status_code == 200, response.text
    minutes = response.json()["expires_in_minutes"]
    assert minutes == settings.jwt_remember_days * 24 * 60
    assert _cookie_max_age(response) == minutes * 60


def test_without_remember_session_is_short(client, users) -> None:
    """Без галочки сессия короткая: на чужом устройстве она не останется навсегда."""
    response = client.post(
        "/api/auth/login", json={"username": "staff", "password": STAFF_PASSWORD}
    )
    assert response.json()["expires_in_minutes"] == settings.jwt_expire_minutes
    assert _cookie_max_age(response) == settings.jwt_expire_minutes * 60


def test_logout_clears_session(client, users) -> None:
    """Выход гасит cookie, и панель снова становится гостевой."""
    _login(client, "staff", STAFF_PASSWORD)
    assert 'id="logout-button"' in client.get("/").text

    assert client.post("/api/auth/logout").status_code == 204
    assert 'id="logout-button"' not in client.get("/").text


def test_stale_cookie_does_not_pretend_to_be_a_session(client, users) -> None:
    """Битый токен — это гость, а не «вошедший» сотрудник."""
    client.cookies.set("ep_token", "broken-token")
    page = client.get("/")
    assert page.status_code == 200
    assert 'id="logout-button"' not in page.text


# ── Шапка ───────────────────────────────────────────────────────────────────

def test_header_shows_shift_owner_and_exit(client, users) -> None:
    """В шапке видно, кто на смене, и есть выход — раньше только в панели кухни."""
    _login(client, "staff", STAFF_PASSWORD)
    page = client.get("/")
    assert 'class="top__who"' in page.text
    assert 'id="logout-button"' in page.text
    assert ">Выйти</button>" in page.text


def test_guest_header_has_no_staff_links(client) -> None:
    """У гостя в шапке нет рабочих разделов."""
    page = client.get("/")
    assert 'id="logout-button"' not in page.text
    assert 'href="/scan"' not in page.text
    assert 'href="/staff"' not in page.text


def test_service_admin_gets_places_not_shift(client, super_admin) -> None:
    """Администратору сервиса «Смена» не показывается: она всё равно ведёт обратно."""
    _login(client, "superadmin", SUPER_PASSWORD)
    page = client.get("/super")
    assert page.status_code == 200
    assert 'href="/super" aria-current="page"' in page.text
    assert 'href="/staff"' not in page.text, "ссылка на смену только путает: его туда не пустят"


def test_staff_nav_marks_current_section(client, users) -> None:
    """Текущий раздел отмечен: видно, где находишься."""
    _login(client, "staff", STAFF_PASSWORD)
    page = client.get("/staff")
    assert 'href="/staff" aria-current="page"' in page.text
    assert 'top__nav--staff' in page.text, "меню смены должно быть помечено для мобильной вёрстки"


# ── Возврат из вложенных страниц ────────────────────────────────────────────

def test_scan_page_has_back_link(client, staff_headers) -> None:
    """Со сканера есть явный возврат к очереди."""
    page = client.get("/scan")
    assert page.status_code == 200
    assert 'class="back-link"' in page.text
    assert "К очереди заказов" in page.text


def test_poster_page_has_back_link_for_staff(client, staff_headers, establishment) -> None:
    """Плакат открыт всем, но сотруднику нужен путь назад в панель."""
    page = client.get(f"/e/{establishment.id}/qr")
    assert page.status_code == 200
    assert 'class="back-link"' in page.text
    assert "К панели смены" in page.text


def test_poster_page_has_no_back_link_for_guests(client, establishment) -> None:
    """Гостю на плакате возврат в панель не показываем — ему туда не надо."""
    page = client.get(f"/e/{establishment.id}/qr")
    assert 'class="back-link"' not in page.text


def test_analytics_page_has_single_nav(client, admin_headers, establishment) -> None:
    """У сводки одно меню — в шапке, плюс возврат. Своё меню только путало."""
    page = client.get("/admin/analytics")
    assert page.status_code == 200
    assert 'class="back-link"' in page.text
    assert 'id="analytics-out"' not in page.text, "выход теперь общий, в шапке"
