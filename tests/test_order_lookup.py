"""Публичный доступ к заказу по коду: короткий код не должен перебираться.

Код заказа — 4 символа из 25-значного алфавита, это 390 625 комбинаций.
Случайность сама по себе перебор не останавливает, поэтому промахи по коду
копят блокировку. При этом обычный гость, который смотрит свой заказ,
лимит не тратит: считается только неудачный поиск.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api_utils import order_lookup_limiter
from tests.conftest import next_local_slot, order_payload

ALPHABET = "ACDEFGHJKMNPQRTUVWXY34679"


def _make_order(client: TestClient, establishment, menu, key: str) -> str:
    response = client.post(
        "/api/orders",
        json=order_payload(establishment.id, [(menu[0].id, 1)], next_local_slot(), key=key),
    )
    assert response.status_code == 201, response.text
    return response.json()["order_code"]


def _wrong_code(index: int) -> str:
    """Заведомо несуществующий, но синтаксически верный код."""
    body = ALPHABET[index % 25] + ALPHABET[(index // 25) % 25] + "AA"
    return f"EX-{body}"


def test_own_order_can_be_viewed_many_times(client: TestClient, establishment,
                                            menu) -> None:
    """Гость смотрит свой заказ сколько нужно — лимит на это не тратится."""
    order_lookup_limiter.reset()
    code = _make_order(client, establishment, menu, "lookup-own-001")

    statuses = [client.get(f"/api/orders/{code}/status").status_code for _ in range(40)]
    assert set(statuses) == {200}, f"свой заказ перестал открываться: {set(statuses)}"

    # И отменить его тоже можно: успешный поиск не приближает блокировку.
    assert client.post(f"/api/orders/{code}/cancel").status_code == 200


def test_wrong_codes_are_limited(client: TestClient) -> None:
    """Перебор кодов упирается в 429: промахи копят блокировку."""
    order_lookup_limiter.reset()

    statuses = [client.get(f"/api/orders/{_wrong_code(i)}/status").status_code
                for i in range(40)]
    assert 404 in statuses, "неверный код должен давать 404"
    assert 429 in statuses, "перебор не ограничен"
    # Блокировка наступает после небольшого числа промахов, а не в конце.
    first_block = statuses.index(429)
    assert first_block <= 15, f"слишком поздно: {first_block} попыток до блокировки"


def test_limited_lookup_blocks_cancel_too(client: TestClient) -> None:
    """Отмена тоже закрыта: иначе подбор кода позволяет отменять чужие заказы."""
    order_lookup_limiter.reset()
    for i in range(20):
        client.get(f"/api/orders/{_wrong_code(i)}/status")

    response = client.post(f"/api/orders/{_wrong_code(99)}/cancel")
    assert response.status_code == 429, response.text


def test_bad_syntax_does_not_spend_the_limit(client: TestClient) -> None:
    """Кривой код отсекается проверкой формата и лимит не расходует.

    Иначе гость, который ошибся раскладкой, блокировал бы себя сам.
    """
    order_lookup_limiter.reset()
    for _ in range(30):
        assert client.get("/api/orders/XXX/status").status_code == 400

    # После тридцати опечаток нормальный поиск всё ещё работает.
    assert client.get(f"/api/orders/{_wrong_code(1)}/status").status_code == 404


def test_forwarded_header_is_ignored_by_default(client: TestClient) -> None:
    """Заголовку X-Forwarded-For по умолчанию не верим.

    Иначе ограничение обходится одной строкой в запросе: подставил другой
    адрес — и лимит снова пуст.
    """
    order_lookup_limiter.reset()
    first = client.get(f"/api/orders/{_wrong_code(1)}/status",
                       headers={"X-Forwarded-For": "10.0.0.1"})
    assert first.status_code == 404
    # Тот же клиент, но с другим «адресом» в заголовке — лимит общий.
    for i in range(20):
        client.get(f"/api/orders/{_wrong_code(i)}/status",
                   headers={"X-Forwarded-For": f"10.0.0.{i}"})

    blocked = client.get(f"/api/orders/{_wrong_code(2)}/status",
                         headers={"X-Forwarded-For": "10.9.9.9"})
    assert blocked.status_code == 429, "лимит обошли подменой заголовка"
