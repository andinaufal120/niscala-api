"""add a version to properties, rooms, tenants, managers and user accounts

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-12 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("properties", "rooms", "tenants", "managers", "user_accounts")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        )


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, "version")
