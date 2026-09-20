"""Начальные данные: заведения, меню и учётные записи.

Отдельный файл, потому что здесь проверяется именно `app/init_db.py`:
идемпотентность наполнения и состав создаваемых аккаунтов.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.init_db import seed
from app.models.enums import StaffRole
from app.models.establishment import Establishment
from app.models.staff_user import StaffUser


def test_seed_creates_superadmin_account(db: Session) -> None:
    """После init_db есть хотя бы один администратор сервиса.

    Без него некому заводить заведения: раздел /super закрыт для всех.
    """
    seed(db)
    db.commit()

    supers = list(db.scalars(select(StaffUser).where(StaffUser.is_super.is_(True))))
    assert supers, "администратор сервиса не создан"

    superadmin = supers[0]
    assert superadmin.username == settings.seed_superadmin_username
    # Роль именно `staff`, а не `admin`: заведение у администратора сервиса
    # своё отсутствует, и роль заведения открыла бы ему меню, слоты и настройки
    # несуществующей точки. Его права держит флаг is_super, а рабочий экран — /super.
    assert superadmin.role == StaffRole.STAFF.value
    assert superadmin.is_admin is False, "администратор сервиса не админ конкретной точки"
    assert superadmin.can_manage_places is True
    # Администратор сервиса не относится ни к одной точке: иначе он занимал бы
    # чужое заведение и в списке выглядел администратором первого кафе.
    assert superadmin.establishment_id is None


def test_seed_is_idempotent_for_superadmin(db: Session) -> None:
    """Повторный запуск не создаёт второго администратора сервиса."""
    seed(db)
    db.commit()
    first = list(db.scalars(select(StaffUser).where(StaffUser.is_super.is_(True))))

    seed(db)
    db.commit()
    second = list(db.scalars(select(StaffUser).where(StaffUser.is_super.is_(True))))

    assert len(second) == len(first) == 1
    assert {user.username for user in second} == {settings.seed_superadmin_username}


def test_seed_marks_existing_superadmin(db: Session) -> None:
    """Существующему аккаунту без признака администратора сервиса признак выдаётся.

    Так выглядит переход: аккаунт завели раньше, признак появился позже.
    Пароль при этом не меняется — иначе смена потеряла бы доступ.
    """
    from app.models.establishment import Establishment
    from app.security import hash_password, verify_password

    seed(db)
    db.commit()

    # Убираем созданного сидом супер-администратора и заводим свой — без признака.
    db.query(StaffUser).filter(
        StaffUser.username == settings.seed_superadmin_username
    ).delete()
    db.commit()

    place = db.scalars(select(Establishment).order_by(Establishment.id)).first()
    assert place is not None, "seed должен создать хотя бы одно заведение"

    db.add(StaffUser(
        establishment_id=place.id,
        username=settings.seed_superadmin_username,
        password_hash=hash_password("свой-пароль-12345"),
        role=StaffRole.ADMIN.value,
        is_super=False,
    ))
    db.commit()

    seed(db)
    db.commit()

    refreshed = db.scalars(
        select(StaffUser).where(StaffUser.username == settings.seed_superadmin_username)
    ).one()
    assert refreshed.is_super is True, "признак администратора сервиса не выдан"
    assert verify_password("свой-пароль-12345", refreshed.password_hash), \
        "пароль существующего аккаунта менять нельзя"


def test_seed_can_skip_superadmin(db: Session, monkeypatch) -> None:
    """Настройка seed_superadmin выключает создание администратора сервиса."""
    monkeypatch.setattr(settings, "seed_superadmin", False)

    seed(db)
    db.commit()

    supers = list(db.scalars(select(StaffUser).where(StaffUser.is_super.is_(True))))
    assert not supers, "администратор сервиса создан, хотя настройка выключена"

def test_superadmin_does_not_occupy_a_place(db: Session) -> None:
    """Администратор сервиса не занимает чужое заведение.

    Раньше колонка была обязательной, и он числился администратором первого
    кафе: карточка в разделе заведений показывала «точка: superadmin» вместо
    реального администратора точки.
    """
    seed(db)
    db.commit()

    superadmin = db.scalars(
        select(StaffUser).where(StaffUser.is_super.is_(True))
    ).all()
    assert len(superadmin) == 1
    assert superadmin[0].establishment_id is None

    # У каждой точки при этом есть свой администратор и своя кухня.
    places = list(db.scalars(select(Establishment).order_by(Establishment.id)))
    assert places, "seed должен создать заведения"
    for place in places:
        users = list(db.scalars(
            select(StaffUser).where(StaffUser.establishment_id == place.id)
        ))
        assert any(user.is_admin for user in users), f"у «{place.name}» нет администратора"
        assert any(not user.is_admin for user in users), f"у «{place.name}» нет кухни"


def test_seed_releases_superadmin_from_an_old_place(db: Session) -> None:
    """Повторный запуск снимает с администратора сервиса чужое заведение.

    Так выглядит переход: аккаунт завели раньше, когда заведение было
    обязательным.
    """
    seed(db)
    db.commit()

    superadmin = db.scalars(select(StaffUser).where(StaffUser.is_super.is_(True))).one()
    # Возвращаем привязку, как было до миграции.
    superadmin.establishment_id = db.scalars(
        select(Establishment).order_by(Establishment.id)
    ).first().id
    db.commit()

    seed(db)
    db.commit()
    db.refresh(superadmin)
    assert superadmin.establishment_id is None, "чужое заведение не снято"
