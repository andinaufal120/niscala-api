"""create complaint photos

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-07 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "complaint_photos",
        sa.Column("complaint_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["complaint_id"],
            ["complaints.id"],
            name=op.f("fk_complaint_photos_complaint_id_complaints"),
        ),
        sa.PrimaryKeyConstraint("complaint_id", name=op.f("pk_complaint_photos")),
    )


def downgrade() -> None:
    op.drop_table("complaint_photos")
