"""Наполнение БД: создание таблиц и начальных данных (раздел 2.7 ТЗ).

Запуск: python -m app.init_db [--reset]

Пароли начальных учётных записей не хардкодятся: берутся из .env
(SEED_ADMIN_PASSWORD / SEED_STAFF_PASSWORD), а при отсутствии — генерируются
случайно и печатаются в консоль один раз.
"""

from __future__ import annotations

import argparse
import sys
from datetime import time
from decimal import Decimal

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, SessionLocal, engine, session_scope
from app.logging_utils import get_logger, setup_logging
from app.models.enums import StaffRole
from app.models.establishment import Establishment
from app.models.menu_item import MenuItem
from app.models.staff_user import StaffUser
from app.security import hash_password
from app.utils.codes import generate_password

logger = get_logger("init_db")

# Витрина: три заведения с фото, рейтингом и кухней.
PLACES: tuple[dict, ...] = (
    {
        "name": "Кафе Central",
        "address": "ул. Абая, 15",
        "cuisine": "Домашняя кухня",
        "photo": "/static/img/places/central.jpg",
        "rating": "4.9",
        "reviews_count": 412,
        "opens_at": time(9, 0),
        "closes_at": time(18, 0),
        "slot_duration_minutes": 5,
        "slot_capacity": 3,
        "baseline_orders_per_day": 35,
        "menu": (
            ("Плов с бараниной", "Основные блюда", "Рис, баранина, морковь, зира",
             "1800.00", 12, "/static/img/menu/plov.jpg", True),
            ("Куриный суп-лапша", "Супы", "Домашняя лапша и курица",
             "1200.00", 7, "/static/img/menu/soup.jpg", True),
            ("Борщ со сметаной", "Супы", "Свёкла, капуста, говядина, сметана",
             "1350.00", 8, "/static/img/menu/borsch.jpg", True),
            ("Салат «Цезарь»", "Салаты", "Курица, романо, пармезан, сухарики",
             "1650.00", 6, "/static/img/menu/caesar.jpg", True),
            ("Стейк из индейки", "Основные блюда", "Индейка на гриле с овощами",
             "2400.00", 15, "/static/img/menu/turkey.jpg", True),
            ("Самса с говядиной", "Выпечка", "Слоёное тесто, сочная говядина",
             "650.00", 5, "/static/img/menu/samsa.jpg", True),
            ("Чай чёрный с молоком", "Напитки", "Крепкий чай с молоком",
             "350.00", 2, "/static/img/menu/tea.jpg", True),
            ("Чизкейк Нью-Йорк", "Десерты", "Сливочный сыр, песочная основа",
             "1100.00", 3, "/static/img/menu/cheesecake.jpg", True),
            ("Мороженое пломбир", "Десерты", "Ванильный пломбир",
             "700.00", 2, "/static/img/menu/icecream.jpg", False),
        ),
    },
    {
        "name": "Green Bowl",
        "address": "пр. Достык, 128",
        "cuisine": "Здоровая еда",
        "photo": "/static/img/places/green.jpg",
        "rating": "4.7",
        "reviews_count": 268,
        "opens_at": time(8, 0),
        "closes_at": time(21, 0),
        "slot_duration_minutes": 5,
        "slot_capacity": 4,
        "baseline_orders_per_day": 48,
        "menu": (
            ("Боул с киноа", "Боулы", "Киноа, авокадо, шпинат, семена",
             "2200.00", 9, "/static/img/menu/caesar.jpg", True),
            ("Смузи «Зелёный»", "Напитки", "Шпинат, яблоко, банан, лайм",
             "1100.00", 4, "/static/img/menu/compote.jpg", True),
            ("Суп-пюре из тыквы", "Супы", "Тыква, имбирь, сливки",
             "1400.00", 6, "/static/img/menu/soup.jpg", True),
            ("Салат с тунцом", "Салаты", "Тунец, фасоль, яйцо, оливки",
             "1900.00", 7, "/static/img/menu/caesar.jpg", True),
            ("Чизкейк без сахара", "Десерты", "На кокосовом сахаре",
             "1250.00", 3, "/static/img/menu/cheesecake.jpg", True),
        ),
    },
    {
        "name": "Кофе и выпечка",
        "address": "ул. Панфилова, 92",
        "cuisine": "Кофейня",
        "photo": "/static/img/places/cup.jpg",
        "rating": "4.8",
        "reviews_count": 531,
        "opens_at": time(7, 30),
        "closes_at": time(20, 0),
        "slot_duration_minutes": 5,
        "slot_capacity": 6,
        "baseline_orders_per_day": 120,
        "menu": (
            ("Капучино", "Кофе", "Двойной эспрессо и молоко",
             "1100.00", 3, "/static/img/menu/tea.jpg", True),
            ("Круассан с миндалём", "Выпечка", "Слоёный, с миндальным кремом",
             "950.00", 2, "/static/img/menu/baursak.jpg", True),
            ("Самса с говядиной", "Выпечка", "Слоёное тесто, сочная говядина",
             "650.00", 5, "/static/img/menu/samsa.jpg", True),
            ("Чизкейк Нью-Йорк", "Десерты", "Сливочный сыр, песочная основа",
             "1100.00", 3, "/static/img/menu/cheesecake.jpg", True),
        ),
    },
)


def tables_exist() -> bool:
    return bool(inspect(engine).get_table_names())


def create_schema() -> None:
    Base.metadata.create_all(bind=engine)
    logger.info("Схема БД готова (%s)", engine.url.render_as_string(hide_password=True))


def drop_schema() -> None:
    Base.metadata.drop_all(bind=engine)
    logger.warning("Все таблицы удалены (--reset)")


def _ensure_places(db: Session) -> list[Establishment]:
    """Создаёт заведения из витрины, если их ещё нет. Повторный запуск безопасен."""
    created: list[Establishment] = []
    existing_names = {name for (name,) in db.execute(select(Establishment.name)).all()}

    for spec in PLACES:
        if spec["name"] in existing_names:
            continue
        place = Establishment(
            name=spec["name"],
            address=spec["address"],
            cuisine=spec["cuisine"],
            photo=spec["photo"],
            rating=Decimal(spec["rating"]),
            reviews_count=spec["reviews_count"],
            opens_at=spec["opens_at"],
            closes_at=spec["closes_at"],
            slot_duration_minutes=spec["slot_duration_minutes"],
            slot_capacity=spec["slot_capacity"],
            baseline_orders_per_day=spec["baseline_orders_per_day"],
            baseline_wait_minutes=Decimal("20.00"),
        )
        db.add(place)
        db.flush()
        created.append(place)
        logger.info("Создано заведение %r (id=%s)", place.name, place.id)

    return created


def _ensure_menu(db: Session, place: Establishment, spec: dict) -> int:
    existing = db.scalars(
        select(MenuItem).where(MenuItem.establishment_id == place.id)
    ).all()
    if existing:
        return 0

    for name, category, description, price, prep_time, photo, is_active in spec["menu"]:
        db.add(
            MenuItem(
                establishment_id=place.id,
                name=name,
                category=category,
                description=description,
                photo=photo,
                price=Decimal(price),
                prep_time_minutes=prep_time,
                is_active=is_active,
            )
        )
    db.flush()
    logger.info("Добавлено %s позиций меню в %r", len(spec["menu"]), place.name)
    return len(spec["menu"])


def _ensure_user(
    db: Session,
    establishment: Establishment | None,
    *,
    username: str,
    password: str,
    role: StaffRole,
    is_super: bool = False,
) -> tuple[str, str] | None:
    """Создаёт пользователя, если его ещё нет. Возвращает (логин, пароль) для вывода.

    Если пользователь уже есть, но без признака администратора сервиса —
    выдаём признак: для супер-администратора это и есть цель вызова, а пароль
    существующей учётной записи мы не трогаем.
    """
    existing = db.scalars(select(StaffUser).where(StaffUser.username == username)).first()
    if existing is not None:
        changed = False
        if is_super and not existing.is_super:
            existing.is_super = True
            logger.info("Пользователю %r выдан доступ администратора сервиса", username)
            changed = True
        # Администратор сервиса не должен занимать чужое заведение.
        if is_super and existing.establishment_id is not None:
            existing.establishment_id = None
            changed = True
        if changed:
            db.flush()
        return None

    generated = False
    if not password:
        password = generate_password()
        generated = True

    db.add(
        StaffUser(
            establishment_id=establishment.id if establishment else None,
            username=username,
            password_hash=hash_password(password),
            role=role.value,
            is_super=is_super,
        )
    )
    db.flush()
    logger.info(
        "Создан пользователь %r с ролью %s%s",
        username,
        role.value,
        " (администратор сервиса)" if is_super else "",
    )
    return (username, password) if generated else (username, "<из .env>")


def refresh_showcase(db: Session) -> int:
    """Дополняет витрину фото, рейтингом и описаниями у уже созданных заведений.

    Нужно, когда база создана до появления витрины: id и история заказов
    сохраняются, а карточки получают фото, кухню, рейтинг и описания блюд.
    """
    updated = 0
    for spec in PLACES:
        place = db.scalars(select(Establishment).where(Establishment.name == spec["name"])).first()
        if place is None:
            continue

        place.photo = spec["photo"]
        place.cuisine = spec["cuisine"]
        place.address = place.address or spec["address"]
        place.rating = Decimal(spec["rating"])
        place.reviews_count = spec["reviews_count"]
        updated += 1

        items = {item.name: item for item in db.scalars(
            select(MenuItem).where(MenuItem.establishment_id == place.id)
        ).all()}
        for name, category, description, price, prep_time, photo, is_active in spec["menu"]:
            item = items.get(name)
            if item is None:
                db.add(
                    MenuItem(
                        establishment_id=place.id,
                        name=name,
                        category=category,
                        description=description,
                        photo=photo,
                        price=Decimal(price),
                        prep_time_minutes=prep_time,
                        is_active=is_active,
                    )
                )
                continue
            item.category = item.category or category
            item.description = item.description or description
            item.photo = item.photo or photo
            if item.price == 0:
                item.price = Decimal(price)

    db.flush()
    logger.info("Витрина обновлена: заведений — %s", updated)
    return updated


def seed(db: Session) -> list[tuple[str, str]]:
    """Идемпотентное наполнение: повторный запуск не создаёт дубликатов."""
    created = _ensure_places(db)
    places = db.scalars(select(Establishment).order_by(Establishment.id)).all()

    for place in places:
        spec = next((s for s in PLACES if s["name"] == place.name), None)
        if spec is not None:
            _ensure_menu(db, place, spec)

    if created:
        logger.info("Создано заведений: %s", len(created))

    if not places:
        return []

    credentials: list[tuple[str, str]] = []

    # Администратор сервиса: заводит заведения и выдаёт им доступ.
    # Заведение у него то же, что у остальных начальных аккаунтов: колонка
    # establishment_id обязательная, а для супер-администратора она значения
    # не имеет — он работает со всеми точками сразу.
    if settings.seed_superadmin:
        # Администратор сервиса не относится ни к одной точке: иначе он
        # занимал бы чужое заведение и выглядел её администратором.
        superadmin = _ensure_user(
            db,
            None,
            username=settings.seed_superadmin_username,
            password=settings.seed_admin_password,
            role=StaffRole.ADMIN,
            is_super=True,
        )
        if superadmin:
            credentials.append(superadmin)

    admin = _ensure_user(
        db,
        places[0],
        username=settings.seed_admin_username,
        password=settings.seed_admin_password,
        role=StaffRole.ADMIN,
    )
    if admin:
        credentials.append(admin)

    staff = _ensure_user(
        db,
        places[0],
        username=settings.seed_staff_username,
        password=settings.seed_staff_password,
        role=StaffRole.STAFF,
    )
    if staff:
        credentials.append(staff)

    # Отдельный аккаунт кухни на каждое заведение: смена видит только свои заказы.
    credentials.extend(_ensure_place_accounts(db, places))

    return credentials


# Латинские имена для логинов кухни: кириллицу в логине набирать неудобно.
_KITCHEN_LOGINS = {
    "Кафе Central": "kitchen-central",
    "Green Bowl": "kitchen-bowl",
    "Кофе и выпечка": "kitchen-coffee",
}


def kitchen_username(place: Establishment) -> str:
    """Логин кухни для заведения. Известным точкам — читаемые имена."""
    known = _KITCHEN_LOGINS.get(place.name)
    if known:
        return known
    slug = "".join(
        symbol if symbol.isalnum() and symbol.isascii() else "-"
        for symbol in place.name.lower()
    )
    slug = "-".join(part for part in slug.split("-") if part)
    return f"kitchen-{slug or place.id}"


def admin_username(place: Establishment) -> str:
    """Логин администратора заведения: `place-<номер>`.

    Схема одна на весь проект — тот же вид возвращает раздел /super, поэтому
    карточка заведения показывает логин, который действительно есть в базе.
    """
    return f"place-{place.id}"


def _ensure_place_accounts(
    db: Session, places: list[Establishment]
) -> list[tuple[str, str]]:
    """Создаёт по два аккаунта на каждое заведение: точку и кухню.

    Пароли берём из .env: `SEED_STAFF_PASSWORD` для кухни и `SEED_ADMIN_PASSWORD`
    для администратора точки. Логин подсказывает, за какую точку отвечает человек.

    Раньше здесь создавалась только кухня, и у заведений из начальных данных
    не было администратора: раздел /super показывал у них пустой логин, а войти
    за точку было некому.
    """
    created: list[tuple[str, str]] = []
    for place in places:
        kitchen = kitchen_username(place)
        # Аккаунт под основным логином уже создан выше — не дублируем.
        if kitchen != settings.seed_staff_username:
            account = _ensure_user(
                db,
                place,
                username=kitchen,
                password=settings.seed_staff_password,
                role=StaffRole.STAFF,
            )
            if account:
                created.append(account)

        admin = admin_username(place)
        if admin != settings.seed_admin_username:
            account = _ensure_user(
                db,
                place,
                username=admin,
                password=settings.seed_admin_password,
                role=StaffRole.ADMIN,
            )
            if account:
                created.append(account)
    return created


def print_credentials(credentials: list[tuple[str, str]]) -> None:
    if not credentials:
        print("\nУчётные записи уже существуют — пароли не изменялись.")
        return
    print("\n" + "=" * 62)
    print("  СОЗДАНЫ УЧЁТНЫЕ ЗАПИСИ (сохраните пароли — они не хранятся в открытом виде)")
    print("=" * 62)
    for username, password in credentials:
        print(f"  логин: {username:<18} пароль: {password}")
    print("=" * 62)
    print("  Панель кухни:          http://127.0.0.1:8000/staff")
    print("  Панель администратора: http://127.0.0.1:8000/admin")
    print("  Заведения сервиса:     http://127.0.0.1:8000/super  (только superadmin)")
    print("  Каждый аккаунт kitchen-* видит заказы только своего заведения.")
    print("=" * 62 + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Инициализация БД ThreeFast")
    parser.add_argument("--reset", action="store_true", help="удалить все таблицы и создать заново")
    parser.add_argument(
        "--refresh-showcase",
        action="store_true",
        help="дополнить уже созданные заведения фото, рейтингом и описаниями",
    )
    args = parser.parse_args(argv)

    # Windows-консоль по умолчанию в cp1251: без этого пароли и русский текст
    # выводятся «кракозябрами», а пароль нужно прочитать глазами.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    setup_logging(settings.log_level, settings.log_path)

    if args.reset:
        drop_schema()
    create_schema()

    with session_scope() as db:
        if args.refresh_showcase:
            refresh_showcase(db)
        credentials = seed(db)

    print_credentials(credentials)
    print(f"База данных: {settings.database_url}")
    print("Запуск сервера: uvicorn app.main:app --reload\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
