"""add the manual classification to complaints

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-27 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "complaints", sa.Column("manual_category", sa.String(), nullable=True)
    )
    op.add_column("complaints", sa.Column("manual_urgency", sa.String(), nullable=True))
    op.add_column("complaints", sa.Column("classified_by_id", sa.Uuid(), nullable=True))
    op.add_column(
        "complaints",
        sa.Column("classified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_complaints_manual_urgency"),
        "complaints",
        "manual_urgency IS NULL OR manual_urgency IN ('low', 'medium', 'high')",
    )
    op.create_foreign_key(
        op.f("fk_complaints_classified_by_id_user_accounts"),
        "complaints",
        "user_accounts",
        ["classified_by_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_complaints_classified_by_id_user_accounts"),
        "complaints",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("ck_complaints_manual_urgency"), "complaints", type_="check"
    )
    op.drop_column("complaints", "classified_at")
    op.drop_column("complaints", "classified_by_id")
    op.drop_column("complaints", "manual_urgency")
    op.drop_column("complaints", "manual_category")
