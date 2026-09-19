"""Валидация и нормализация пользовательского ввода (раздел 2.10 ТЗ).

Сообщения об ошибках — на русском и понятные гостю, а не «Validation Error».
"""

from __future__ import annotations

import re

PHONE_ERROR = "Введите номер в формате +7XXXXXXXXXX"
NAME_ERROR = "Имя должно содержать от 2 до 100 символов"

_DIGITS_RE = re.compile(r"\D")


def normalize_phone(raw: str) -> str:
    """Приводит номер к +7XXXXXXXXXX.

    Принимает +7XXXXXXXXXX, 8XXXXXXXXXX, 7XXXXXXXXXX, с пробелами,
    дефисами и скобками. Кидает ValueError с человекочитаемым текстом.
    """
    if raw is None:
        raise ValueError(PHONE_ERROR)
    digits = _DIGITS_RE.sub("", str(raw))
    if not digits:
        raise ValueError(PHONE_ERROR)

    if len(digits) == 11 and digits[0] in {"7", "8"}:
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits

    if len(digits) != 11 or not digits.startswith("7"):
        raise ValueError(PHONE_ERROR)

    # Казахстанские/российские мобильные: +7 7XX / +7 9XX и городские коды.
    if digits[1] not in "3456789":
        raise ValueError(PHONE_ERROR)
    return f"+{digits}"


def is_valid_phone(raw: str) -> bool:
    try:
        normalize_phone(raw)
    except ValueError:
        return False
    return True


def normalize_name(raw: str) -> str:
    """Схлопывает пробелы и проверяет длину имени гостя."""
    if raw is None:
        raise ValueError(NAME_ERROR)
    cleaned = " ".join(str(raw).split())
    if not cleaned or not (2 <= len(cleaned) <= 100):
        raise ValueError(NAME_ERROR)
    return cleaned
