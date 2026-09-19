"""Супер-администратор не привязан к заведению

Revision ID: 0005_superadmin_no_place
Revises: 0004_super_admin
Create Date: 2026-09-20

Администратор сервиса заводит заведения и выдаёт им доступ, но сам не
относится ни к одной точке. Раньше ему приходилось занимать чужое заведение
(колонка была обязательной), и в списке заведений он выглядел администратором
первого кафе: карточка показывала «точка: superadmin» вместо реального
администратора точки.

Миграция идемпотентная: повторный запуск не падает.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_superadmin_no_place"
down_revision: Union[str, None] = "0004_super_admin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _nullable() -> bool:
    inspector = sa.inspect(op.get_bind())
    for column in inspector.get_columns("staff_users"):
        if column["name"] == "establishment_id":
            return bool(column["nullable"])
    return False


def upgrade() -> None:
    if not _nullable():
        with op.batch_alter_table("staff_users") as batch:
            batch.alter_column("establishment_id", existing_type=sa.Integer(), nullable=True)

    # Освобождаем администратора сервиса от чужого заведения.
    op.execute(
        sa.text("UPDATE staff_users SET establishment_id = NULL WHERE is_super = 1")
    )


def downgrade() -> None:
    # Перед возвратом обязательности нужно вернуть привязку: берём первое
    # заведение, иначе вставка NOT NULL упадёт на существующих строках.
    op.execute(
        sa.text(
            "UPDATE staff_users SET establishment_id = "
            "(SELECT MIN(id) FROM establishments) WHERE establishment_id IS NULL"
        )
    )
    if _nullable():
        with op.batch_alter_table("staff_users") as batch:
            batch.alter_column("establishment_id", existing_type=sa.Integer(), nullable=False)
