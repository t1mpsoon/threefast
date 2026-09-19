"""Витрина: фото заведений и блюд, описание и рейтинг.


Revision ID: 0002_showcase
Revises: 0001_initial_schema
Create Date: 2026-09-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_showcase"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    if not _columns("establishments"):
        return

    existing = _columns("establishments")
    with op.batch_alter_table("establishments") as batch:
        if "photo" not in existing:
            batch.add_column(sa.Column("photo", sa.String(length=200), nullable=True))
        if "cuisine" not in existing:
            batch.add_column(sa.Column("cuisine", sa.String(length=50), nullable=True))
        if "rating" not in existing:
            batch.add_column(
                sa.Column("rating", sa.Numeric(2, 1), nullable=False, server_default="4.8")
            )
        if "reviews_count" not in existing:
            batch.add_column(
                sa.Column("reviews_count", sa.Integer(), nullable=False, server_default="0")
            )

    existing = _columns("menu_items")
    with op.batch_alter_table("menu_items") as batch:
        if "description" not in existing:
            batch.add_column(sa.Column("description", sa.String(length=160), nullable=True))
        if "photo" not in existing:
            batch.add_column(sa.Column("photo", sa.String(length=200), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("menu_items") as batch:
        batch.drop_column("photo")
        batch.drop_column("description")
    with op.batch_alter_table("establishments") as batch:
        batch.drop_column("reviews_count")
        batch.drop_column("rating")
        batch.drop_column("cuisine")
        batch.drop_column("photo")
