"""Генерация публичных кодов заказа и ключей идемпотентности (разделы 2.11, 2.14 ТЗ)."""

from __future__ import annotations

import secrets
import string
import uuid
from collections.abc import Callable

# Алфавит без символов, которые легко перепутать при диктовке вслух:
# исключены 0/O, 1/I/L, 2/Z, 5/S, 8/B. Только заглавные буквы и цифры 3,4,6,7,9.
CODE_ALPHABET = "ACDEFGHJKMNPQRTUVWXY34679"
CODE_PREFIX = "EX-"
CODE_LENGTH = 4
_MAX_GENERATION_ATTEMPTS = 50


def generate_order_code() -> str:
    """Короткий код заказа для выдачи: EX-3467 (случайный, не последовательный ID)."""
    body = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    return f"{CODE_PREFIX}{body}"


def generate_unique_order_code(exists: Callable[[str], bool]) -> str:
    """Код, которого ещё нет в БД. `exists` — функция проверки (code) -> bool."""
    for _ in range(_MAX_GENERATION_ATTEMPTS):
        code = generate_order_code()
        if not exists(code):
            return code
    raise RuntimeError("Не удалось сгенерировать уникальный код заказа")


def generate_idempotency_key() -> str:
    """Ключ для клиента: повторная отправка формы не создаст дубль заказа."""
    return uuid.uuid4().hex


def _code_body(raw: str) -> str:
    """Тело кода без префикса. «EX» срезается, только если после него ещё 4 символа:
    алфавит содержит E и X, так что код вроде EX-EXA3 без префикса — это тело «EXA3»."""
    cleaned = "".join(ch for ch in raw.strip().upper() if ch.isalnum())
    if cleaned.startswith("EX") and len(cleaned) > CODE_LENGTH:
        cleaned = cleaned[2:]
    return cleaned


def normalize_order_code(raw: str) -> str:
    """Приводит введённый гостем код к каноническому виду: 'ex3467' -> 'EX-3467'."""
    return f"{CODE_PREFIX}{_code_body(raw)}"


def is_valid_order_code(raw: str) -> bool:
    cleaned = _code_body(raw)
    return len(cleaned) == CODE_LENGTH and all(ch in CODE_ALPHABET for ch in cleaned)


def generate_password(length: int = 12) -> str:
    """Пароль для начальных учётных записей (печатается в консоль, не хардкодится)."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))
