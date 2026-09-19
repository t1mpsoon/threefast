"""Логирование (раздел 2.13 ТЗ).

Формат: [timestamp] [level] [module] message.
Хранение: ./logs/app.log с ротацией по размеру (5 МБ, 5 файлов истории).
Запрещено логировать пароли, JWT-токены и полные номера телефонов.
"""

from __future__ import annotations

import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5

_PHONE_RE = re.compile(r"(?<!\d)(\+?\d{7,15})(?!\d)")
_TOKEN_RE = re.compile(r"\b(eyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,})\b")
_BCRYPT_RE = re.compile(r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}")

_configured = False


def mask_phone(value: object) -> str:
    """Маскирует телефон для логов: +77011234567 -> +7701***67 (раздел 2.13 ТЗ)."""
    if value is None:
        return "—"
    text = str(value)
    digits = re.sub(r"\D", "", text)
    if len(digits) < 6:
        return "***"
    return f"{digits[:4]}***{digits[-2:]}"


def scrub(text: object) -> str:
    """Убирает из строки лога токены, bcrypt-хэши и полные телефоны."""
    value = str(text)
    value = _TOKEN_RE.sub("<token-hidden>", value)
    value = _BCRYPT_RE.sub("<hash-hidden>", value)
    value = _PHONE_RE.sub(lambda m: mask_phone(m.group(1)), value)
    return value


class _ScrubbingFilter(logging.Filter):
    """Страховка: даже при неаккуратном вызове логгера секреты не попадут в файл."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.msg = scrub(record.getMessage())
        record.args = ()
        return True


def setup_logging(level: str = "INFO", log_dir: str | Path = "./logs") -> logging.Logger:
    """Инициализирует корневой логгер приложения (идемпотентно)."""
    global _configured

    logger = logging.getLogger("express_pickup")
    if _configured:
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    scrubber = _ScrubbingFilter()

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(scrubber)
    logger.addHandler(stream_handler)

    try:
        directory = Path(log_dir)
        directory.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            directory / "app.log",
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(scrubber)
        logger.addHandler(file_handler)
    except OSError as exc:  # pragma: no cover - зависит от прав ФС
        logger.warning("Не удалось создать файловый лог в %s: %s", log_dir, exc)

    _configured = True
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Возвращает дочерний логгер приложения."""
    return logging.getLogger("express_pickup" if not name else f"express_pickup.{name}")
