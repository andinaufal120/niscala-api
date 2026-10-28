"""add account status and deletion, and create email change requests

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-29 00:00:01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_accounts",
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
    )
    op.alter_column("user_accounts", "status", server_default=None)
    op.add_column(
        "user_accounts",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_user_accounts_status"),
        "user_accounts",
        "status IN ('active', 'inactive')",
    )
    op.create_table(
        "email_change_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("new_email", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_accounts.id"],
            name=op.f("fk_email_change_requests_user_id_user_accounts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_change_requests")),
        sa.UniqueConstraint(
            "token_hash", name=op.f("uq_email_change_requests_token_hash")
        ),
    )


def downgrade() -> None:
    op.drop_table("email_change_requests")
    op.drop_constraint(op.f("ck_user_accounts_status"), "user_accounts", type_="check")
    op.drop_column("user_accounts", "deleted_at")
    op.drop_column("user_accounts", "status")
