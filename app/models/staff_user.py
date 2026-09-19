"""Сотрудник/администратор заведения (таблица staff_users, раздел 2.7 ТЗ).

Логин/пароль используется только для внутреннего интерфейса. Клиентский
флоу заказа регистрации не требует (раздел 2.19 ТЗ).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import StaffRole

if TYPE_CHECKING:  # pragma: no cover
    from app.models.establishment import Establishment


class StaffUser(Base):
    __tablename__ = "staff_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # У администратора сервиса заведения нет: он работает со всеми сразу.
    establishment_id: Mapped[int | None] = mapped_column(
        ForeignKey("establishments.id", ondelete="CASCADE"), nullable=True, index=True
    )
    username: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=StaffRole.STAFF.value)
    # Супер-администратор сервиса: заводит заведения и выдаёт им доступ.
    # Заведение у него тоже есть — оно используется как «домашнее» для панели.
    is_super: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    establishment: Mapped["Establishment | None"] = relationship(back_populates="staff_users")

    @property
    def role_enum(self) -> StaffRole:
        return StaffRole(self.role)

    @property
    def is_admin(self) -> bool:
        return self.role == StaffRole.ADMIN.value

    @property
    def can_manage_places(self) -> bool:
        """Заводить заведения и выдавать доступ может только супер-администратор."""
        return bool(self.is_super)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<StaffUser {self.username!r} role={self.role}>"
