"""create login failures

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-18 00:00:02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "login_failures",
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "failed_attempts >= 0",
            name=op.f("ck_login_failures_failed_attempts_not_negative"),
        ),
        sa.PrimaryKeyConstraint("email", name=op.f("pk_login_failures")),
    )


def downgrade() -> None:
    op.drop_table("login_failures")
