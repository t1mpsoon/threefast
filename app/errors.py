"""Доменные исключения. Сервисы не знают про HTTP — роутеры/обработчики переводят их в коды."""

from __future__ import annotations


class AppError(Exception):
    """Базовая ошибка приложения с человекочитаемым сообщением для гостя."""

    status_code = 500
    code = "internal_error"
    default_message = "Произошла ошибка, мы уже знаем о ней"

    def __init__(self, message: str | None = None, *, details: dict | None = None) -> None:
        self.message = message or self.default_message
        self.details = details or {}
        super().__init__(self.message)


class InputError(AppError):
    """Некорректные данные, прошедшие схему, но нарушающие бизнес-правила (400).

    Название намеренно не `ValidationError`: так называется исключение pydantic,
    и совпадение имён затрудняет чтение кода.
    """

    status_code = 400
    code = "invalid_input"
    default_message = "Проверьте правильность заполнения полей"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    default_message = "Не найдено"


class SlotUnavailableError(InputError):
    """Слот заняли между шагом 2 и шагом 3 (правило А-2, 409 в разделе 2.8 ТЗ).

    Наследуется от InputError: для гостя это такая же ошибка выбора времени,
    отличается только HTTP-код — 409, чтобы клиент вернул его на шаг 2.
    """

    status_code = 409
    code = "slot_unavailable"
    default_message = "Выбранное время только что заняли, выберите другое"


class VersionConflictError(AppError):
    """Optimistic locking: статус заказа уже изменил другой сотрудник."""

    status_code = 409
    code = "version_conflict"
    default_message = "Статус заказа уже был изменён, обновите страницу"


class ConflictError(AppError):
    """Попытка создать то, что уже есть: занятый логин или повтор названия."""

    status_code = 409
    code = "conflict"
    default_message = "Такая запись уже существует"


class InvalidStatusTransitionError(AppError):
    """Недопустимый переход статуса (правило Б-2)."""

    status_code = 400
    code = "invalid_status_transition"
    default_message = "Недопустимый переход статуса"


class AuthenticationError(AppError):
    status_code = 401
    code = "unauthorized"
    default_message = "Требуется авторизация"


class PermissionDeniedError(AppError):
    status_code = 403
    code = "forbidden"
    default_message = "Недостаточно прав"


class RateLimitError(AppError):
    status_code = 429
    code = "rate_limited"
    default_message = "Слишком много запросов, попробуйте через минуту"
