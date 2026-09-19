"""Фронтенд панели смены должен соответствовать ролевой модели.

Бэкенд уже разделяет роли: настройки, аналитика и правка меню защищены
`require_admin`. Эти тесты проверяют, что интерфейс не обещает кухне того,
чего она сделать не может: иначе сотрудник видит форму, заполняет её и
получает 403 без объяснения.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES = BASE_DIR / "app" / "templates"
STATIC_JS = BASE_DIR / "app" / "static" / "js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _page(client: TestClient, headers: dict[str, str]) -> str:
    """HTML панели смены от имени вошедшего пользователя."""
    response = client.get("/staff", headers=headers, follow_redirects=True)
    assert response.status_code == 200, response.text
    return response.text


# ── Страница: что вообще отдаётся кухне ─────────────────────────────────────
def test_kitchen_page_has_no_admin_tabs(client: TestClient, staff_headers) -> None:
    """Вкладки «Настройки» и «Аналитика» кухне не отдаются вовсе."""
    html = _page(client, staff_headers)

    assert 'data-panel="queue"' in html
    assert 'data-panel="menu"' in html
    assert 'data-panel="settings"' not in html, "вкладка настроек доступна кухне"
    assert 'data-panel="report"' not in html, "вкладка аналитики доступна кухне"


def test_kitchen_page_has_no_menu_editor(client: TestClient, staff_headers) -> None:
    """Формы правки блюда и кнопки добавления у кухни нет в разметке."""
    html = _page(client, staff_headers)

    assert 'id="dish-form"' not in html, "форма правки блюда доступна кухне"
    assert 'id="dish-new"' not in html, "кнопка добавления блюда доступна кухне"
    assert 'id="dish-save"' not in html


def test_kitchen_page_has_no_settings_form(client: TestClient, staff_headers) -> None:
    """Настройки заведения кухне не показываем: ручка требует администратора."""
    html = _page(client, staff_headers)
    assert 'id="settings-form"' not in html
    assert 'id="set-save"' not in html


def test_admin_page_has_all_admin_blocks(client: TestClient, admin_headers) -> None:
    """У администратора заведения всё на месте — мы ничего не отняли."""
    html = _page(client, admin_headers)

    for part in ('data-panel="settings"', 'data-panel="report"', 'id="dish-form"',
                 'id="dish-new"', 'id="settings-form"', 'id="set-save"'):
        assert part in html, f"у администратора пропал блок {part}"


def test_kitchen_still_sees_the_queue(client: TestClient, staff_headers) -> None:
    """Главное действие кухни не тронуто: очередь и смена статуса на месте."""
    html = _page(client, staff_headers)
    assert 'class="crew__board"' in html, "кухня потеряла очередь заказов"
    assert 'id="crew-refresh"' in html

    script = _read(STATIC_JS / "staff_panel.js")
    # Смена статуса заказа — это работа кухни, а не админская операция.
    assert "new_status" in script, "кухня потеряла возможность менять статус"
    assert "if (!button || !isAdmin) return;" in script, \
        "правка меню должна требовать администратора"
    # Обработчик статуса не должен зависеть от роли.
    status_handler = script[script.find("host.addEventListener('click'"):]
    status_handler = status_handler[: status_handler.find("refresh.addEventListener")]
    assert "isAdmin" not in status_handler, "смена статуса не должна зависеть от роли"


# ── Скрипт: соответствие ручек и элементов управления ───────────────────────
def test_script_hides_admin_controls_from_kitchen() -> None:
    """Все admin-only ручки закрыты на фронтенде проверкой роли."""
    script = _read(STATIC_JS / "staff_panel.js")

    assert "var isAdmin = root.dataset.role === 'admin';" in script
    assert "if (name === 'settings' && isAdmin)" in script, "настройки грузятся без проверки"
    assert "if (name === 'report' && isAdmin)" in script, "аналитика грузится без проверки"

    # Кнопки правки рисуем только администратору, кухне — бейдж просмотра.
    assert "function menuSideHtml(item)" in script
    assert "if (!isAdmin)" in script and "только просмотр" in script

    # Элементы редактора могут отсутствовать в разметке — обращения защищены.
    for element in ("dish-new", "dish-cancel", "dish-reset", "dish-photo"):
        assert f"document.getElementById('{element}')" in script
    assert "if (dishNew)" in script, "обработчик кнопки добавления без защиты"
    assert "if (form) form.addEventListener" in script, "форма правки без защиты"


def test_every_element_used_by_script_exists_in_template() -> None:
    """Скрипт не обращается к элементам, которых нет ни в разметке, ни в его вёрстке.

    Часть узлов скрипт создаёт сам через innerHTML — например строку с новым
    паролем. Такие id проверять в шаблоне бессмысленно: их там и не должно быть.
    """
    script = _read(STATIC_JS / "staff_panel.js")
    template = _read(TEMPLATES / "staff" / "queue.html")

    # id, которые встречаются внутри строк с разметкой: скрипт их и создаёт.
    generated = set(re.findall(r"id=\\?[\"']([a-z0-9-]+)\\?[\"']", script))
    used = set(re.findall(r"getElementById\('([a-z0-9-]+)'\)", script))

    missing = sorted(
        name for name in used
        if f'id="{name}"' not in template and name not in generated
    )
    assert not missing, f"скрипт ищет то, чего нет в разметке: {missing}"


def test_kitchen_api_matches_the_interface(client: TestClient, staff_headers,
                                           admin_headers) -> None:
    """Ручки отвечают так же, как обещает интерфейс: кухне 403, админу 200."""
    # То, что кухне недоступно.
    for method, url, payload in (
        ("put", "/api/staff/settings", {
            "opens_at": "09:00", "closes_at": "21:00", "slot_duration_minutes": 5,
            "slot_capacity": 3, "baseline_orders_per_day": 35, "baseline_wait_minutes": 20,
        }),
        ("get", "/api/staff/analytics", None),
        ("post", "/api/staff/menu", {
            "name": "Тестовое блюдо", "price": 500, "prep_time_minutes": 5,
        }),
    ):
        call = getattr(client, method)
        response = call(url, headers=staff_headers) if payload is None else \
            call(url, json=payload, headers=staff_headers)
        assert response.status_code == 403, f"{method.upper()} {url}: {response.status_code}"

    # То, что кухне доступно и осталось доступным.
    assert client.get("/api/staff/orders", headers=staff_headers).status_code == 200
    assert client.get("/api/staff/menu", headers=staff_headers).status_code == 200

    # Администратор те же ручки выполняет.
    assert client.get("/api/staff/analytics", headers=admin_headers).status_code == 200

def test_superadmin_has_no_shift_panel(client: TestClient, client_admin) -> None:
    """Администратор сервиса не попадает в панель смены.

    Своего заведения у него нет, поэтому очередь была бы пустой и он решил бы,
    что заказов нет. Его рабочий экран — список заведений.
    """
    response = client.get("/staff", headers=client_admin, follow_redirects=False)
    assert response.status_code == 303, response.text
    assert response.headers["location"] == "/super"


def test_superadmin_gets_a_clear_answer_from_staff_api(client, client_admin) -> None:
    """Ручки смены отвечают понятной ошибкой, а не пустым списком."""
    for path in ("/api/staff/orders", "/api/staff/queue-stats", "/api/staff/menu"):
        response = client.get(path, headers=client_admin)
        assert response.status_code == 400, f"{path}: {response.status_code}"
        assert "нет своего заведения" in response.json()["detail"], response.text


def test_superadmin_identity_has_no_place(client_admin, client: TestClient) -> None:
    """/api/staff/me отдаёт администратора сервиса без заведения.

    Раньше он числился администратором первого кафе и карточка в списке
    заведений показывала «точка: superadmin» вместо реального администратора.
    """
    response = client.get("/api/staff/me", headers=client_admin)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_super"] is True
    assert body["establishment_id"] is None
    assert body["establishment_name"] == ""
