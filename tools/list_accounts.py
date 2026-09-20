"""Показывает ровно те учётные записи, которые создаёт сидирование.

Запускается на временной SQLite, поэтому боевую базу не трогает.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TEMP_DB = Path(tempfile.gettempdir()) / "accounts_probe.db"
TEMP_DB.unlink(missing_ok=True)

# Те же переменные, что заданы в render.yaml на хостинге.
os.environ["DATABASE_URL"] = f"sqlite:///{TEMP_DB.as_posix()}"
os.environ["SECRET_KEY"] = "probe-secret-key"
os.environ["ENABLE_SCHEDULER"] = "false"
os.environ["SEED_ADMIN_PASSWORD"] = "<из SEED_ADMIN_PASSWORD>"
os.environ["SEED_STAFF_PASSWORD"] = "<из SEED_STAFF_PASSWORD>"
os.environ["SEED_SUPERADMIN"] = "true"
os.environ["SEED_SUPERADMIN_USERNAME"] = "superadmin"
os.environ["SEED_ADMIN_USERNAME"] = "admin"
os.environ["SEED_STAFF_USERNAME"] = "staff"

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal, Base, engine  # noqa: E402
from app.init_db import seed  # noqa: E402
from app.models.establishment import Establishment  # noqa: E402
from app.models.staff_user import StaffUser  # noqa: E402

Base.metadata.create_all(bind=engine)

with SessionLocal() as db:
    seed(db)
    db.commit()

    places = {p.id: p.name for p in db.scalars(select(Establishment)).all()}
    users = db.scalars(select(StaffUser).order_by(StaffUser.id)).all()

    print(f"Заведений: {len(places)}")
    for pid, name in sorted(places.items()):
        print(f"  id={pid}  {name}")
    print()
    print(f"Всего учётных записей: {len(users)}")
    print()
    print(f"{'логин':<18} {'роль':<7} {'админ сервиса':<14} заведение")
    print("-" * 72)
    for u in users:
        place = places.get(u.establishment_id, "— (нет заведения)") if u.establishment_id else "— (нет заведения)"
        print(f"{u.username:<18} {u.role:<7} {('да' if u.is_super else 'нет'):<14} {place}")
    print()
    print("может заводить заведения (/super):", [u.username for u in users if u.can_manage_places])
    print("пройдёт проверку require_admin (/admin):", [u.username for u in users if u.is_admin])
