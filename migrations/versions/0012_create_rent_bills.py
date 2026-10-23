"""create rent bills, their status changes and receipts

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-23 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUS = "IN ('unpaid', 'awaitingVerification', 'paid', 'rejected')"
METHOD = "IN ('transfer', 'cash')"


def upgrade() -> None:
    op.create_table(
        "rent_bills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("lease_id", sa.Uuid(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("payment_status", sa.String(), nullable=False),
        sa.Column("payment_method", sa.String(), nullable=True),
        sa.Column("paid_on", sa.Date(), nullable=True),
        sa.Column("rejection_reason", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount > 0", name=op.f("ck_rent_bills_amount_positive")),
        sa.CheckConstraint(
            f"payment_status {STATUS}", name=op.f("ck_rent_bills_payment_status")
        ),
        sa.CheckConstraint(
            f"payment_method IS NULL OR payment_method {METHOD}",
            name=op.f("ck_rent_bills_payment_method"),
        ),
        sa.ForeignKeyConstraint(
            ["lease_id"], ["leases.id"], name=op.f("fk_rent_bills_lease_id_leases")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rent_bills")),
        sa.UniqueConstraint(
            "lease_id", "period_start", name=op.f("uq_rent_bills_lease_id")
        ),
    )
    op.create_table(
        "rent_bill_status_changes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rent_bill_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("method", sa.String(), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("manual", sa.Boolean(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"status {STATUS}", name=op.f("ck_rent_bill_status_changes_status")
        ),
        sa.CheckConstraint(
            f"method IS NULL OR method {METHOD}",
            name=op.f("ck_rent_bill_status_changes_method"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["user_accounts.id"],
            name=op.f("fk_rent_bill_status_changes_actor_id_user_accounts"),
        ),
        sa.ForeignKeyConstraint(
            ["rent_bill_id"],
            ["rent_bills.id"],
            name=op.f("fk_rent_bill_status_changes_rent_bill_id_rent_bills"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rent_bill_status_changes")),
    )
    op.create_table(
        "rent_bill_receipts",
        sa.Column("rent_bill_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["rent_bill_id"],
            ["rent_bills.id"],
            name=op.f("fk_rent_bill_receipts_rent_bill_id_rent_bills"),
        ),
        sa.PrimaryKeyConstraint("rent_bill_id", name=op.f("pk_rent_bill_receipts")),
    )


def downgrade() -> None:
    op.drop_table("rent_bill_receipts")
    op.drop_table("rent_bill_status_changes")
    op.drop_table("rent_bills")
