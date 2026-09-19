"""Аутентификация персонала и администратора (JWT, раздел 2.14 ТЗ).

Клиентский флоу регистрации не требует — логин/пароль нужен только
сотрудникам заведения для доступа к панелям.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.api_utils import client_ip, login_limiter
from app.config import settings
from app.database import get_db
from app.errors import AuthenticationError, InputError, RateLimitError
from app.models.enums import StaffRole
from app.security import (
    TOKEN_COOKIE_NAME,
    authenticate,
    create_access_token,
    get_current_user,
    require_admin,
    hash_password,
)
from app.schemas.auth import LoginRequest, StaffUserCreate, StaffUserOut, TokenResponse
from app.models.staff_user import StaffUser
from app.repositories.staff_repository import StaffRepository

router = APIRouter(prefix="/api/auth", tags=["Авторизация"])


@router.post("/login", response_model=TokenResponse, summary="Вход сотрудника/администратора")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Проверяет логин/пароль и выдаёт JWT.

    Токен дублируется в httpOnly-cookie, чтобы HTML-панели работали без JS-хранилища.
    """
    limiter_key = f"login:{client_ip(request)}"
    wait = login_limiter.retry_after(limiter_key)
    if wait:
        raise RateLimitError(f"Слишком много неудачных попыток входа. Повторите через {wait} сек.")

    user = authenticate(db, payload.username, payload.password)
    if user is None:
        login_limiter.penalize(limiter_key)
        raise AuthenticationError("Неверный логин или пароль")
    login_limiter.reset(limiter_key)

    token, expires_minutes = create_access_token(user)
    response.set_cookie(
        key=TOKEN_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=expires_minutes * 60,
        path="/",
    )
    return TokenResponse(
        access_token=token,
        expires_in_minutes=expires_minutes,
        username=user.username,
        role=user.role,
        role_title=StaffRole(user.role).title,
        establishment_id=user.establishment_id,
        establishment_name=user.establishment.name if user.establishment else "",
        can_manage_places=user.can_manage_places,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Выход")
def logout(response: Response) -> Response:
    response.delete_cookie(TOKEN_COOKIE_NAME, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=StaffUserOut, summary="Текущий пользователь")
def me(user: StaffUser = Depends(get_current_user)) -> StaffUserOut:
    return StaffUserOut.model_validate(user)


@router.post(
    "/users",
    response_model=StaffUserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Создать сотрудника (только администратор)",
)
def create_user(
    payload: StaffUserCreate,
    admin: StaffUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> StaffUserOut:
    repository = StaffRepository(db)
    if repository.get_by_username(payload.username) is not None:
        raise InputError("Пользователь с таким логином уже существует")

    user = StaffUser(
        establishment_id=admin.establishment_id,
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    repository.create(user)
    db.commit()
    db.refresh(user)
    return StaffUserOut.model_validate(user)


@router.get("/session", summary="Проверка активной сессии (для HTML-панелей)")
def session_info(request: Request, user: StaffUser = Depends(get_current_user)) -> dict:
    return {
        "username": user.username,
        "role": user.role,
        "role_title": StaffRole(user.role).title,
        "establishment_id": user.establishment_id,
    }
