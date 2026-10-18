"""create complaints and complaint status changes

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-18 00:00:09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUS = "status IN ('new', 'inProgress', 'done')"


def upgrade() -> None:
    op.create_table(
        "complaints",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("classification_state", sa.String(), nullable=True),
        sa.Column("ai_category", sa.String(), nullable=True),
        sa.Column("ai_urgency", sa.String(), nullable=True),
        sa.Column("ai_suggested_action", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(STATUS, name=op.f("ck_complaints_status")),
        sa.CheckConstraint(
            "classification_state IS NULL OR classification_state IN "
            "('classifying', 'awaitingClassification', 'notClassified')",
            name=op.f("ck_complaints_classification_state"),
        ),
        sa.CheckConstraint(
            "ai_urgency IS NULL OR ai_urgency IN ('low', 'medium', 'high')",
            name=op.f("ck_complaints_ai_urgency"),
        ),
        sa.ForeignKeyConstraint(
            ["room_id"], ["rooms.id"], name=op.f("fk_complaints_room_id_rooms")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.user_id"],
            name=op.f("fk_complaints_tenant_id_tenants"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_complaints")),
    )
    op.create_table(
        "complaint_status_changes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("complaint_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("handling_note", sa.String(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(STATUS, name=op.f("ck_complaint_status_changes_status")),
        sa.ForeignKeyConstraint(
            ["complaint_id"],
            ["complaints.id"],
            name=op.f("fk_complaint_status_changes_complaint_id_complaints"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_complaint_status_changes")),
    )


def downgrade() -> None:
    op.drop_table("complaint_status_changes")
    op.drop_table("complaints")
