"""Общие фикстуры тестов.

Тесты идут на временной SQLite-базе: рабочая data/express_pickup.db не затрагивается.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

# Переменные окружения выставляются ДО импорта приложения.
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest")
os.environ.setdefault("ENABLE_SCHEDULER", "false")
# Тесты наполняют БД сами: автосидирование перезаписало бы тестовых пользователей.
os.environ["SEED_ON_STARTUP"] = "false"
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("RATE_LIMIT_ORDERS_PER_MINUTE", "1000")
_TMP_DB = Path(tempfile.gettempdir()) / "express_pickup_tests.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.database import Base, engine, get_db  # noqa: E402
from app.models.enums import StaffRole  # noqa: E402
from app.models.establishment import Establishment  # noqa: E402
from app.models.menu_item import MenuItem  # noqa: E402
from app.models.staff_user import StaffUser  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.utils.rate_limit import RateLimiter  # noqa: E402

ADMIN_PASSWORD = "admin-test-pass"
STAFF_PASSWORD = "staff-test-pass"
SUPER_PASSWORD = "super-test-pass"

TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


@pytest.fixture(scope="session", autouse=True)
def _schema() -> None:
    """Создаёт схему один раз на всю тестовую сессию."""
    Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def _clean_state(_schema) -> None:
    """Перед каждым тестом — пустые таблицы и сброшенный rate limiter."""
    from app.api_utils import order_lookup_limiter, order_rate_limiter

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    order_rate_limiter.reset()
    # Лимит на подбор кода заказа живёт в памяти процесса: без сброса он
    # переносился бы между тестами и валил чужие проверки на ровном месте.
    order_lookup_limiter.reset()
    yield
    order_rate_limiter.reset()


@pytest.fixture
def db() -> Session:
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def establishment(db: Session) -> Establishment:
    """Заведение, открытое с 00:00 до 23:55, чтобы слоты были доступны в любой час."""
    item = Establishment(
        name="Тестовое кафе",
        address="г. Алматы, ул. Тестовая 1",
        opens_at=time(0, 0),
        closes_at=time(23, 55),
        slot_duration_minutes=5,
        slot_capacity=2,
        baseline_orders_per_day=35,
        baseline_wait_minutes=Decimal("20.00"),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@pytest.fixture
def menu(db: Session, establishment: Establishment) -> list[MenuItem]:
    items = [
        MenuItem(
            establishment_id=establishment.id,
            name="Плов",
            category="Основные блюда",
            price=Decimal("1800.00"),
            prep_time_minutes=12,
            is_active=True,
        ),
        MenuItem(
            establishment_id=establishment.id,
            name="Чай",
            category="Напитки",
            price=Decimal("350.00"),
            prep_time_minutes=2,
            is_active=True,
        ),
        MenuItem(
            establishment_id=establishment.id,
            name="Скрытое блюдо",
            category="Прочее",
            price=Decimal("500.00"),
            prep_time_minutes=5,
            is_active=False,
        ),
    ]
    db.add_all(items)
    db.commit()
    for item in items:
        db.refresh(item)
    return items


@pytest.fixture
def users(db: Session, establishment: Establishment) -> dict[str, StaffUser]:
    admin = StaffUser(
        establishment_id=establishment.id,
        username="admin",
        password_hash=hash_password(ADMIN_PASSWORD),
        role=StaffRole.ADMIN.value,
    )
    staff = StaffUser(
        establishment_id=establishment.id,
        username="staff",
        password_hash=hash_password(STAFF_PASSWORD),
        role=StaffRole.STAFF.value,
    )
    db.add_all([admin, staff])
    db.commit()
    db.refresh(admin)
    db.refresh(staff)
    return {"admin": admin, "staff": staff}


@pytest.fixture
def client(_clean_state, establishment: Establishment, menu, users) -> TestClient:
    """HTTP-клиент с изолированной БД на каждый тест.

    Планировщик в тестах выключен (ENABLE_SCHEDULER=false), поэтому lifespan
    не запускает фоновые задачи.
    """
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def staff_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login", json={"username": "staff", "password": STAFF_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def admin_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


# ── Помощники для тестов ────────────────────────────────────────────────────
def next_local_slot(minutes_ahead: int = 30, *, step: int = 5) -> datetime:
    """Ближайшее время в будущем, кратное шагу сетки слотов."""
    moment = datetime.now() + timedelta(minutes=minutes_ahead)
    remainder = moment.minute % step
    if remainder:
        moment += timedelta(minutes=step - remainder)
    return moment.replace(second=0, microsecond=0)


@pytest.fixture
def slot_time() -> datetime:
    return next_local_slot()


def order_payload(
    establishment_id: int,
    item_ids: list[tuple[int, int]],
    slot_datetime: datetime,
    *,
    key: str = "test-idempotency-key-1",
    name: str = "Аружан",
    phone: str = "+77011234567",
) -> dict:
    return {
        "establishment_id": establishment_id,
        "slot_datetime": slot_datetime.isoformat(),
        "guest_name": name,
        "guest_phone": phone,
        "items": [{"menu_item_id": item_id, "quantity": qty} for item_id, qty in item_ids],
        "payment_method": "cash_on_pickup",
        "idempotency_key": key,
    }

@pytest.fixture
def super_admin(db: Session, establishment: Establishment) -> StaffUser:
    """Администратор сервиса: заводит заведения и видит платформу целиком."""
    user = StaffUser(
        # Как и в настоящем приложении: администратор сервиса не относится
        # ни к одной точке.
        establishment_id=None,
        username="superadmin",
        password_hash=hash_password(SUPER_PASSWORD),
        role=StaffRole.ADMIN.value,
        is_super=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def client_admin(client: TestClient, super_admin: StaffUser) -> dict[str, str]:
    """Заголовки администратора сервиса."""
    response = client.post(
        "/api/auth/login", json={"username": super_admin.username, "password": SUPER_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
