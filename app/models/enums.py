"""Роли пользователей внутреннего интерфейса (раздел 2.19 ТЗ: только staff и admin)."""

from __future__ import annotations

from enum import StrEnum


class StaffRole(StrEnum):
    STAFF = "staff"
    ADMIN = "admin"

    @property
    def title(self) -> str:
        return {"staff": "Сотрудник кухни", "admin": "Администратор"}[self.value]
