"""Признак супер-администратора сервиса

Revision ID: 0004_super_admin
Revises: 0003_order_note
Create Date: 2026-09-20

Супер-администратор заводит заведения и выдаёт им доступ в панель.
Миграция идемпотентная: повторный запуск не падает.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_super_admin"
down_revision: Union[str, None] = "0003_order_note"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    if "is_super" not in _columns("staff_users"):
        with op.batch_alter_table("staff_users") as batch:
            batch.add_column(
                sa.Column("is_super", sa.Boolean(), nullable=False, server_default=sa.false())
            )


def downgrade() -> None:
    if "is_super" in _columns("staff_users"):
        with op.batch_alter_table("staff_users") as batch:
            batch.drop_column("is_super")
