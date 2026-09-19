"""Конфигурация приложения: загрузка и валидация переменных окружения (раздел 2.12 ТЗ)."""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Корень проекта (папка, содержащая app/)
BASE_DIR = Path(__file__).resolve().parent.parent

_INSECURE_DEFAULT_SECRET = "change_me_to_random_value"


class Settings(BaseSettings):
    """Настройки из .env. Все секреты — только здесь, в коде их нет (раздел 2.14 ТЗ)."""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Приложение ─────────────────────────────────────────────────────────
    app_env: str = "development"
    app_title: str = "ThreeFast"

    # ── База данных ────────────────────────────────────────────────────────
    database_url: str = "sqlite:///./data/express_pickup.db"

    # ── Безопасность ───────────────────────────────────────────────────────
    secret_key: str = _INSECURE_DEFAULT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    # ── Бизнес-параметры ───────────────────────────────────────────────────
    default_slot_duration_minutes: int = Field(default=5, ge=1, le=240)
    default_slot_capacity: int = Field(default=3, ge=1, le=1000)
    order_expire_after_ready_minutes: int = Field(default=20, ge=1, le=1440)
    max_booking_days_ahead: int = Field(default=7, ge=1, le=60)

    # ── Логирование ────────────────────────────────────────────────────────
    log_level: str = "INFO"
    log_dir: str = "./logs"

    # ── Ограничения корзины и анти-спам ────────────────────────────────────
    rate_limit_orders_per_minute: int = Field(default=5, ge=1, le=1000)
    max_quantity_per_item: int = Field(default=20, ge=1, le=100)
    max_distinct_items_per_order: int = Field(default=15, ge=1, le=100)

    # ── Начальные данные ───────────────────────────────────────────────────
    seed_admin_username: str = "admin"
    seed_admin_password: str = ""
    seed_staff_username: str = "staff"
    seed_staff_password: str = ""
    # Администратор сервиса: заводит заведения и выдаёт им доступ.
    # Пароль берётся из seed_admin_password — отдельного поля не заводим,
    # чтобы не плодить секреты в .env.
    seed_superadmin: bool = True
    seed_superadmin_username: str = "superadmin"

    # Верить заголовку X-Forwarded-For. Включать только когда приложение
    # стоит за своим прокси: иначе клиент подставит любой адрес и обойдёт
    # ограничение по IP.
    trust_proxy_headers: bool = False

    # ── Планировщик ────────────────────────────────────────────────────────
    enable_scheduler: bool = True
    # Наполнять БД начальными данными при старте приложения (в тестах выключено).
    seed_on_startup: bool = True

    @field_validator("app_env")
    @classmethod
    def _validate_env(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"development", "production"}:
            raise ValueError("APP_ENV должен быть 'development' или 'production'")
        return normalized

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if level not in allowed:
            raise ValueError(f"LOG_LEVEL должен быть одним из {sorted(allowed)}")
        return level

    # ── Производные свойства ───────────────────────────────────────────────
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_memory_db(self) -> bool:
        return ":memory:" in self.database_url

    @property
    def log_path(self) -> Path:
        path = Path(self.log_dir)
        return path if path.is_absolute() else (BASE_DIR / path)

    def ensure_secret_key(self) -> str:
        """Гарантирует наличие рабочего SECRET_KEY.

        В development при отсутствии ключа он генерируется на время процесса
        (с предупреждением). В production небезопасное значение — фатальная ошибка.
        """
        if self.secret_key and self.secret_key != _INSECURE_DEFAULT_SECRET:
            return self.secret_key
        if self.is_production:
            raise RuntimeError(
                "SECRET_KEY не задан. Укажите надёжный ключ в .env перед запуском "
                "в production (python -c \"import secrets; print(secrets.token_urlsafe(48))\")"
            )
        self.secret_key = secrets.token_urlsafe(48)
        return self.secret_key


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Кэшированный доступ к настройкам (один экземпляр на процесс)."""
    return Settings()


settings = get_settings()
