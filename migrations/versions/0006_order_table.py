"""Столик в заказе

Revision ID: 0006_order_table
Revises: 0005_superadmin_no_place
Create Date: 2026-09-20

Гость выбирает столик при оформлении, а метка со QR-плаката (`?src=table5`)
подставляет номер заранее. Кухня видит столик в очереди и в карточке заказа,
чтобы вынести заказ, а не выкликивать номер.

Колонка необязательная: заказ на вынос идёт без столика.
Миграция идемпотентная: повторный запуск не падает, если колонка уже есть.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_order_table"
down_revision: Union[str, None] = "0005_superadmin_no_place"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    if "table_number" not in _columns("orders"):
        with op.batch_alter_table("orders") as batch:
            batch.add_column(sa.Column("table_number", sa.Integer(), nullable=True))


def downgrade() -> None:
    if "table_number" in _columns("orders"):
        with op.batch_alter_table("orders") as batch:
            batch.drop_column("table_number")
