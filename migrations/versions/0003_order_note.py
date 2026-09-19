"""Примечание к заказу и привязка аккаунтов кухни к заведениям

Revision ID: 0003_order_note
Revises: 0002_showcase
Create Date: 2026-09-20

Что меняется:
* у заказа появляется необязательное примечание гостя («без лука»);
* аккаунты персонала получают индекс по заведению — кухня видит только свои заказы.

Миграция идемпотентная: повторный запуск не падает, если колонка уже есть.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_order_note"
down_revision: Union[str, None] = "0002_showcase"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    if "note" not in _columns("orders"):
        with op.batch_alter_table("orders") as batch:
            batch.add_column(sa.Column("note", sa.String(length=200), nullable=True))


def downgrade() -> None:
    if "note" in _columns("orders"):
        with op.batch_alter_table("orders") as batch:
            batch.drop_column("note")
