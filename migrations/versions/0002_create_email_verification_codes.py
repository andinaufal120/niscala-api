"""create email verification codes

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-18 00:00:01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_verification_codes",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "failed_attempts >= 0",
            name=op.f("ck_email_verification_codes_failed_attempts_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_accounts.id"],
            name=op.f("fk_email_verification_codes_user_id_user_accounts"),
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_email_verification_codes")),
    )


def downgrade() -> None:
    op.drop_table("email_verification_codes")
