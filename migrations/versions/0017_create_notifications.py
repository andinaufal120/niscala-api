"""create notifications and notification settings, and add session push tokens

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-29 00:00:03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TYPE = (
    "type IN ('billIssued', 'dueDateReminder', 'billOverdue', "
    "'paymentStatusChanged', 'complaintStatusChanged', 'complaintSubmitted', "
    "'receiptUploaded', 'cashPaymentRecorded', 'tenantActivated', "
    "'managerActivated')"
)
CATEGORY = (
    "category IN ('billing', 'paymentStatus', 'complaintProgress', "
    "'newComplaint', 'receiptUpload', 'overdueBill', 'accountActivity')"
)
URGENCY_SCOPE = "urgency_scope IS NULL OR urgency_scope IN ('allUrgencies', 'highOnly')"


def upgrade() -> None:
    op.add_column("sessions", sa.Column("push_token", sa.String(), nullable=True))
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recipient_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(TYPE, name=op.f("ck_notifications_type")),
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
            name=op.f("fk_notifications_property_id_properties"),
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["user_accounts.id"],
            name=op.f("fk_notifications_recipient_id_user_accounts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index(
        op.f("ix_notifications_recipient_id"), "notifications", ["recipient_id"]
    )
    op.create_table(
        "notification_settings",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("push_enabled", sa.Boolean(), nullable=False),
        sa.Column("urgency_scope", sa.String(), nullable=True),
        sa.CheckConstraint(CATEGORY, name=op.f("ck_notification_settings_category")),
        sa.CheckConstraint(
            URGENCY_SCOPE, name=op.f("ck_notification_settings_urgency_scope")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_accounts.id"],
            name=op.f("fk_notification_settings_user_id_user_accounts"),
        ),
        sa.PrimaryKeyConstraint(
            "user_id", "category", name=op.f("pk_notification_settings")
        ),
    )


def downgrade() -> None:
    op.drop_table("notification_settings")
    op.drop_index(op.f("ix_notifications_recipient_id"), table_name="notifications")
    op.drop_table("notifications")
    op.drop_column("sessions", "push_token")
