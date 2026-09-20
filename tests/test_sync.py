"""Синхронизация кухни и гостя: статус заказа доезжает до экрана гостя сам.

Проверки появились после реального дефекта. Сразу после оформления гость
попадал на экран успеха, у которого не было `id="order-card"`, и скрипт
`order_status.js` выходил, не начиная опрос: гость видел «принят», пока кухня
уже готовила, — ровно до перезагрузки страницы. Тогда же нашёлся и
`staff_queue.js`, который правили как очередь кухни, хотя его никто не
подключал.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from tests.conftest import next_local_slot, order_payload

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_JS = BASE_DIR / "app" / "static" / "js"
TEMPLATES = BASE_DIR / "app" / "templates"


def _create(client: TestClient, establishment, menu, key: str = "sync-key-0001") -> dict:
    response = client.post(
        "/api/orders",
        json=order_payload(establishment.id, [(menu[0].id, 1)], next_local_slot(), key=key),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _move(client: TestClient, headers: dict, order_id: int, version: int, target: str) -> int:
    response = client.patch(
        f"/api/staff/orders/{order_id}/status",
        headers=headers,
        json={"new_status": target, "version": version},
    )
    assert response.status_code == 200, response.text
    return response.json()["version"]


def test_status_is_never_cached(client, establishment, menu) -> None:
    """Статус нельзя кэшировать: иначе гость видит устаревшую карточку."""
    code = _create(client, establishment, menu)["order_code"]
    response = client.get(f"/api/orders/{code}/status")
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-store"


def test_status_carries_headline_for_each_step(client, staff_headers, establishment, menu) -> None:
    """Заголовок экрана приходит с сервера — та же формулировка, что у кухни."""
    created = _create(client, establishment, menu, key="sync-key-0002")
    code, order_id, version = created["order_code"], created["order_id"], 1

    first = client.get(f"/api/orders/{code}/status").json()
    assert first["status"] == "confirmed"
    assert first["status_headline"] == "принят"
    assert first["is_active"] is True

    for target, headline in (("in_progress", "готовят"), ("ready", "готов!")):
        version = _move(client, staff_headers, order_id, version, target)
        assert client.get(f"/api/orders/{code}/status").json()["status_headline"] == headline

    _move(client, staff_headers, order_id, version, "picked_up")
    final = client.get(f"/api/orders/{code}/status").json()
    assert final["status_headline"] == "выдан"
    assert final["is_active"] is False, "завершённый заказ не должен просить опрос"


def test_success_screen_is_alive(client, establishment, menu) -> None:
    """Экран сразу после оформления обязан участвовать в опросе статуса."""
    code = _create(client, establishment, menu, key="sync-key-0003")["order_code"]
    page = client.get(f"/order?code={code}&fresh=1")
    assert page.status_code == 200
    html = page.text
    assert 'id="order-card"' in html, "без этого order_status.js не начинает опрос"
    assert f'data-code="{code}"' in html
    assert 'data-role="headline"' in html, "заголовок не обновится при смене статуса"
    assert 'data-role="state"' in html, "плашка статуса не обновится"
    assert "data-progress" in html, "шкала прогресса не обновится"


def test_success_screen_shows_real_step(client, establishment, menu) -> None:
    """Шкала на экране успеха стоит на «Принят», а не забегает на «Готовится»."""
    code = _create(client, establishment, menu, key="sync-key-0004")["order_code"]
    html = client.get(f"/order?code={code}&fresh=1").text
    assert 'data-status="confirmed"' in html
    assert 'data-step="1"' in html


def test_guest_polls_only_while_order_is_active() -> None:
    """Опрос статуса идёт, пока заказ в работе, и прекращается на завершённом."""
    js = (STATIC_JS / "order_status.js").read_text(encoding="utf-8")
    assert "POLL_MS = 5000" in js, "статус должен подтягиваться заметно чаще прежних 15 секунд"
    assert "order.is_active" in js, "опрос должен опираться на признак активности с сервера"
    assert "document.hidden" in js, "в скрытой вкладке сервер не дёргаем"


def test_kitchen_queue_refreshes_itself() -> None:
    """Очередь смены подтягивается сама, но не перерисовывается впустую."""
    js = (STATIC_JS / "staff_panel.js").read_text(encoding="utf-8")
    poll = re.search(
        r"window\.setInterval\(function \(\) \{(.*?)\},\s*(\d+)\);", js, re.S
    )
    assert poll, "не найден автозапуск обновления очереди"
    assert "loadOrders()" in poll.group(1), "интервал должен перечитывать очередь"
    assert "document.hidden" in poll.group(1), "в скрытой вкладке сервер не дёргаем"
    assert int(poll.group(2)) <= 10000, f"очередь обновляется слишком редко: {poll.group(2)} мс"
    assert "queueSignature" in js, "без отпечатка список перерисовывался бы впустую"


def test_every_script_is_wired_to_a_template() -> None:
    """В статике не должно быть скриптов-сирот.

    Так нашёлся `staff_queue.js`: его правили как очередь кухни, хотя файл
    никто не подключал — настоящую панель рисует `staff_panel.js`.
    """
    templates = "\n".join(path.read_text(encoding="utf-8") for path in TEMPLATES.rglob("*.html"))
    orphans = [
        path.relative_to(STATIC_JS).as_posix()
        for path in STATIC_JS.rglob("*.js")
        if f"/static/js/{path.relative_to(STATIC_JS).as_posix()}" not in templates
    ]
    assert not orphans, f"скрипты, которые никуда не подключены: {orphans}"
