"""Тесты валидации, безопасности и логирования (разделы 2.10, 2.13, 2.14 ТЗ)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import BASE_DIR
from app.logging_utils import mask_phone, scrub
from app.security import (
    authenticate,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.utils.codes import (
    generate_order_code,
    generate_unique_order_code,
    is_valid_order_code,
    normalize_order_code,
)
from app.utils.time_utils import humanize_slot, parse_date, parse_slot_datetime
from app.utils.validators import normalize_name, normalize_phone
from tests.conftest import ADMIN_PASSWORD


# ── Валидация телефона и имени (раздел 2.10 ТЗ) ─────────────────────────────
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+77011234567", "+77011234567"),
        ("87011234567", "+77011234567"),
        ("7 701 123 45 67", "+77011234567"),
        ("+7 (701) 123-45-67", "+77011234567"),
        ("77011234567", "+77011234567"),
        ("7011234567", "+77011234567"),
    ],
)
def test_phone_normalization(raw: str, expected: str) -> None:
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["12345", "", "abc", "+1 202 555 0143", "00000000000"])
def test_invalid_phone_rejected(raw: str) -> None:
    with pytest.raises(ValueError) as error:
        normalize_phone(raw)
    assert "формат" in str(error.value)


@pytest.mark.parametrize(
    "raw,expected",
    [("  Аружан  ", "Аружан"), ("Аружан  Кусаинова", "Аружан Кусаинова"), ("А Б", "А Б")],
)
def test_name_normalization(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


@pytest.mark.parametrize("raw", ["", " ", "А", "   Б   "])
def test_invalid_name_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_name(raw)


# ── Коды заказов ────────────────────────────────────────────────────────────
def test_order_code_format_and_alphabet() -> None:
    code = generate_order_code()
    assert code.startswith("EX-")
    assert len(code) == 7
    # Буквы и цифры, которые нельзя перепутать при диктовке (0/O, 1/I/L, 2/Z, 5/S, 8/B).
    assert all(character in "ACDEFGHJKMNPQRTUVWXY34679" for character in code[3:])


def test_order_code_normalization() -> None:
    assert normalize_order_code("ex3467") == "EX-3467"
    assert normalize_order_code(" EX-3467 ") == "EX-3467"
    assert normalize_order_code("3467") == "EX-3467"


def test_order_code_validation() -> None:
    valid_code = generate_order_code()
    assert is_valid_order_code(valid_code) is True
    assert is_valid_order_code(valid_code.lower()) is True
    assert is_valid_order_code("EX-7841") is False  # 8 и 1 вне алфавита
    assert is_valid_order_code("123") is False
    assert is_valid_order_code("EX-ACDEF") is False  # длина больше 4


def test_unique_code_generation_avoids_collisions() -> None:
    taken = {generate_order_code() for _ in range(3)}
    code = generate_unique_order_code(lambda candidate: candidate in taken)
    assert code not in taken


# ── Пароли и JWT (раздел 2.14 ТЗ) ───────────────────────────────────────────
def test_password_hash_is_not_plaintext() -> None:
    hashed = hash_password("super-secret-1")
    assert "super-secret-1" not in hashed
    assert hashed.startswith("$2")
    assert verify_password("super-secret-1", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_long_password_handled_without_error() -> None:
    """bcrypt ограничен 72 байтами — длинный пароль не должен ломать вход."""
    long_password = "п" * 200
    hashed = hash_password(long_password)
    assert verify_password(long_password, hashed) is True


def test_same_password_gives_different_hashes() -> None:
    assert hash_password("same-password") != hash_password("same-password")


def test_authenticate_unknown_user_returns_none(db) -> None:
    assert authenticate(db, "ghost", "any-password") is None


def test_authenticate_correct_credentials(db, users) -> None:
    user = authenticate(db, "admin", ADMIN_PASSWORD)
    assert user is not None
    assert user.is_admin is True


def test_jwt_round_trip(users) -> None:
    token, expires = create_access_token(users["staff"])
    payload = decode_access_token(token)
    assert payload["sub"] == str(users["staff"].id)
    assert payload["role"] == "staff"
    assert expires > 0


def test_tampered_token_rejected(users) -> None:
    from app.errors import AuthenticationError

    token, _ = create_access_token(users["staff"])
    tampered = token[:-3] + "abc"
    with pytest.raises(AuthenticationError):
        decode_access_token(tampered)


# ── Логирование: маскирование секретов (раздел 2.13 ТЗ) ─────────────────────
def test_phone_masking() -> None:
    assert mask_phone("+77011234567") == "7701***67"
    assert mask_phone(None) == "—"
    assert mask_phone("123") == "***"


def test_scrub_removes_secrets() -> None:
    text = "Заказ для +77011234567 токен eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcdefghijk"
    cleaned = scrub(text)
    assert "77011234567" not in cleaned
    assert "eyJhbGciOiJIUzI1NiJ9" not in cleaned
    assert "***" in cleaned


# ── Утилиты времени ─────────────────────────────────────────────────────────
def test_parse_date_variants() -> None:
    assert parse_date("2026-09-19").isoformat() == "2026-09-19"
    assert parse_date("19.09.2026") is None
    assert parse_date("") is None
    assert parse_date(None) is None


def test_parse_slot_datetime_handles_zulu_and_offset() -> None:
    assert parse_slot_datetime("2026-09-19T13:05:00Z") is not None
    assert parse_slot_datetime("2026-09-19T13:05:00+05:00").hour == 13
    assert parse_slot_datetime("2026-09-19T13:05:37") .second == 0
    assert parse_slot_datetime("not-a-date") is None


def test_humanize_slot_prefixes() -> None:
    from datetime import datetime, timedelta

    now = datetime(2026, 9, 19, 12, 0)
    assert humanize_slot(datetime(2026, 9, 19, 13, 5), now).startswith("Сегодня")
    assert humanize_slot(datetime(2026, 9, 20, 13, 5), now).startswith("Завтра")
    assert "сентября" in humanize_slot(datetime(2026, 9, 25, 13, 5), now)


# ── Секреты не должны попадать в репозиторий (раздел 2.14 ТЗ) ───────────────
def test_env_is_gitignored() -> None:
    gitignore = (BASE_DIR / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore


def test_env_example_has_no_real_secret() -> None:
    content = (BASE_DIR / ".env.example").read_text(encoding="utf-8")
    assert "change_me_to_random_value" in content


def test_source_files_have_no_hardcoded_secret() -> None:
    """В коде не должно быть присвоений вида SECRET_KEY = '<длинная строка>'."""
    import re

    pattern = re.compile(r"SECRET_KEY\s*=\s*['\"][A-Za-z0-9_\-]{20,}['\"]")
    offenders: list[str] = []
    for path in (BASE_DIR / "app").rglob("*.py"):
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(BASE_DIR)))
    assert not offenders, f"найдены хардкод-секреты: {offenders}"


# ── Обработка ошибок (раздел 2.11 ТЗ) ───────────────────────────────────────
def test_api_returns_json_error_with_code(client: TestClient) -> None:
    response = client.get("/api/establishments/999999/menu")
    assert response.status_code == 404
    body = response.json()
    assert set(body) >= {"detail", "code"}
    assert "Traceback" not in response.text


def test_unknown_api_route_returns_404_json(client: TestClient) -> None:
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_validation_error_lists_fields(client: TestClient) -> None:
    response = client.post("/api/orders", json={"establishment_id": 1})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert isinstance(body["fields"], dict)
    assert body["fields"], "должны быть перечислены проблемные поля"


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_docs_available(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


# ── Валидация схем ──────────────────────────────────────────────────────────
def test_order_schema_rejects_duplicate_items() -> None:
    from pydantic import ValidationError as PydanticValidationError

    from app.schemas.order import OrderCreateRequest

    with pytest.raises(PydanticValidationError):
        OrderCreateRequest(
            establishment_id=1,
            slot_datetime="2026-09-19T13:05:00",
            guest_name="Аружан",
            guest_phone="+77011234567",
            items=[
                {"menu_item_id": 1, "quantity": 1},
                {"menu_item_id": 1, "quantity": 2},
            ],
            idempotency_key="key-12345678",
        )


def test_menu_item_schema_validates_price() -> None:
    from pydantic import ValidationError as PydanticValidationError

    from app.schemas.menu import MenuItemCreate

    with pytest.raises(PydanticValidationError):
        MenuItemCreate(name="Суп", price=Decimal("0"), prep_time_minutes=5)
    with pytest.raises(PydanticValidationError):
        MenuItemCreate(name="Суп", price=Decimal("200000"), prep_time_minutes=5)
