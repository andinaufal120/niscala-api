"""create used refresh tokens

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-19 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "used_refresh_tokens",
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name=op.f("fk_used_refresh_tokens_session_id_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_used_refresh_tokens")),
    )
    op.create_index(
        op.f("ix_used_refresh_tokens_session_id"),
        "used_refresh_tokens",
        ["session_id"],
    )
    op.execute(
        "INSERT INTO used_refresh_tokens (token_hash, session_id, rotated_at) "
        "SELECT previous_refresh_token_hash, id, last_active_at FROM sessions "
        "WHERE previous_refresh_token_hash IS NOT NULL"
    )
    op.drop_column("sessions", "previous_refresh_token_hash")


def downgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("previous_refresh_token_hash", sa.String(), nullable=True),
    )
    op.execute(
        "UPDATE sessions SET previous_refresh_token_hash = ("
        "SELECT token_hash FROM used_refresh_tokens "
        "WHERE used_refresh_tokens.session_id = sessions.id "
        "ORDER BY rotated_at DESC LIMIT 1)"
    )
    op.drop_index(
        op.f("ix_used_refresh_tokens_session_id"), table_name="used_refresh_tokens"
    )
    op.drop_table("used_refresh_tokens")
