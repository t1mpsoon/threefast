"""Доступ к данным сотрудников и администраторов."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models.staff_user import StaffUser


class StaffRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, user_id: int) -> StaffUser | None:
        stmt = (
            select(StaffUser).options(joinedload(StaffUser.establishment)).where(StaffUser.id == user_id)
        )
        return self.db.scalars(stmt).first()

    def get_by_username(self, username: str) -> StaffUser | None:
        stmt = (
            select(StaffUser)
            .options(joinedload(StaffUser.establishment))
            .where(func.lower(StaffUser.username) == username.strip().lower())
        )
        return self.db.scalars(stmt).first()

    def create(self, user: StaffUser) -> StaffUser:
        self.db.add(user)
        self.db.flush()
        return user
