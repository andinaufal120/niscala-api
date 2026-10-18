"""create subscriptions

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-18 00:00:04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("plan", sa.String(), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "plan IN ('basic', 'pro')", name=op.f("ck_subscriptions_plan")
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["user_accounts.id"],
            name=op.f("fk_subscriptions_owner_id_user_accounts"),
        ),
        sa.PrimaryKeyConstraint("owner_id", name=op.f("pk_subscriptions")),
    )


def downgrade() -> None:
    op.drop_table("subscriptions")
