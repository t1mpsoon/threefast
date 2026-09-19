"""Pydantic-схемы аутентификации персонала и администратора (раздел 2.10 ТЗ)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=1, max_length=200)

    @field_validator("username")
    @classmethod
    def _clean_username(cls, value: str) -> str:
        return value.strip()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    username: str
    role: str
    role_title: str
    # У администратора сервиса заведения нет: он работает со всеми сразу.
    establishment_id: int | None = None
    establishment_name: str = ""
    # Супер-администратор сервиса: ему доступно управление заведениями.
    can_manage_places: bool = False


class StaffUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str
    establishment_id: int | None = None


class StaffUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=200)
    role: str = Field(default="staff", pattern="^(staff|admin)$")

    @field_validator("username")
    @classmethod
    def _clean_username(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 3:
            raise ValueError("Логин должен содержать от 3 до 50 символов")
        return cleaned

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Пароль должен содержать минимум 8 символов")
        return value
