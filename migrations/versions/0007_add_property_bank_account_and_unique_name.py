"""add property bank account and unique name

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-18 00:00:06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("properties", sa.Column("bank_name", sa.String(), nullable=True))
    op.add_column(
        "properties", sa.Column("bank_account_number", sa.String(), nullable=True)
    )
    op.add_column(
        "properties", sa.Column("bank_account_holder_name", sa.String(), nullable=True)
    )
    op.create_index(
        op.f("uq_properties_owner_name"),
        "properties",
        ["owner_id", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(op.f("uq_properties_owner_name"), table_name="properties")
    op.drop_column("properties", "bank_account_holder_name")
    op.drop_column("properties", "bank_account_number")
    op.drop_column("properties", "bank_name")
