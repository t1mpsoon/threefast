"""Безопасность: хэширование паролей, JWT, зависимости авторизации (раздел 2.14 ТЗ).

ОТКЛОНЕНИЕ ОТ ТЗ: в разделе 2.16 указан `passlib[bcrypt]`, но passlib 1.7.4
(последний релиз) несовместим с современными версиями bcrypt (обращается к
удалённому `bcrypt.__about__`) и падает на Python 3.11+. Здесь используется
библиотека `bcrypt` напрямую — функциональность та же, зависимость надёжнее.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, Request
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.errors import AuthenticationError, PermissionDeniedError
from app.logging_utils import get_logger
from app.models.enums import StaffRole
from app.models.staff_user import StaffUser
from app.repositories.staff_repository import StaffRepository

logger = get_logger("security")

BCRYPT_MAX_BYTES = 72
PASSWORD_MIN_LENGTH = 8

TOKEN_COOKIE_NAME = "ep_token"


class _DummyHash:
    """Фиктивный хэш для выравнивания времени ответа при несуществующем логине."""

    value = bcrypt.hashpw(b"dummy-password-for-timing", bcrypt.gensalt(rounds=12))


def hash_password(password: str) -> str:
    """bcrypt-хэш пароля. Длинные пароли безопасно обрезаются по границе байт."""
    if not password:
        raise ValueError("Пароль не может быть пустым")
    payload = password.encode("utf-8")[:BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(payload, bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if not password or not password_hash:
        return False
    try:
        payload = password.encode("utf-8")[:BCRYPT_MAX_BYTES]
        return bcrypt.checkpw(payload, password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def authenticate(db: Session, username: str, password: str) -> StaffUser | None:
    """Проверяет логин/пароль. Возвращает пользователя или None."""
    user = StaffRepository(db).get_by_username(username)
    if user is None:
        # Считаем «пустой» хэш, чтобы не раскрывать существование логина по времени.
        bcrypt.checkpw(password.encode("utf-8")[:BCRYPT_MAX_BYTES], _DummyHash.value)
        logger.warning("Неудачный вход: пользователь %r не найден", username)
        return None
    if not verify_password(password, user.password_hash):
        logger.warning("Неудачный вход: неверный пароль для %r", username)
        return None
    logger.info("Вход сотрудника %r (роль %s)", user.username, user.role)
    return user


# ── JWT ─────────────────────────────────────────────────────────────────────
def create_access_token(user: StaffUser) -> tuple[str, int]:
    """Возвращает (токен, срок действия в минутах)."""
    expires_minutes = settings.jwt_expire_minutes
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=expires_minutes)).timestamp()),
    }
    token = jwt.encode(payload, settings.ensure_secret_key(), algorithm=settings.jwt_algorithm)
    return token, expires_minutes


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(
            token, settings.ensure_secret_key(), algorithms=[settings.jwt_algorithm]
        )
    except JWTError as exc:
        raise AuthenticationError("Сессия истекла, войдите заново") from exc


# ── Зависимости FastAPI ─────────────────────────────────────────────────────
def _extract_token(request: Request) -> str | None:
    """Токен из заголовка Authorization: Bearer <token> либо из cookie (для HTML-панелей)."""
    header = request.headers.get("Authorization") or request.headers.get("authorization")
    if header:
        scheme, _, credentials = header.partition(" ")
        if scheme.lower() == "bearer" and credentials:
            return credentials.strip()
    cookie = request.cookies.get(TOKEN_COOKIE_NAME)
    return cookie or None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> StaffUser:
    """Текущий авторизованный сотрудник (401, если токена нет/он невалиден)."""
    token = _extract_token(request)
    if not token:
        raise AuthenticationError()
    payload = decode_access_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise AuthenticationError()
    user = StaffRepository(db).get(int(user_id))
    if user is None:
        raise AuthenticationError("Пользователь не найден, войдите заново")
    return user


def require_super(user: StaffUser = Depends(get_current_user)) -> StaffUser:
    """Только супер-администратор сервиса: заведения и доступы."""
    if not user.can_manage_places:
        raise PermissionDeniedError("Раздел доступен только администратору сервиса")
    return user


def require_admin(user: StaffUser = Depends(get_current_user)) -> StaffUser:
    """Только администратор заведения: меню, слоты, аналитика (раздел 2.14 ТЗ)."""
    if user.role != StaffRole.ADMIN.value:
        raise PermissionDeniedError("Действие доступно только администратору заведения")
    return user


def require_staff(user: StaffUser = Depends(get_current_user)) -> StaffUser:
    """Любой сотрудник заведения: очередь заказов и смена статусов (Ф-6)."""
    return user
