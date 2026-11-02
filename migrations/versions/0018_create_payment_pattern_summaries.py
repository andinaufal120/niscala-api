"""create payment pattern summaries

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-02 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payment_pattern_summaries",
        sa.Column("lease_id", sa.Uuid(), nullable=False),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["lease_id"],
            ["leases.id"],
            name=op.f("fk_payment_pattern_summaries_lease_id_leases"),
        ),
        sa.PrimaryKeyConstraint("lease_id", name=op.f("pk_payment_pattern_summaries")),
    )


def downgrade() -> None:
    op.drop_table("payment_pattern_summaries")
