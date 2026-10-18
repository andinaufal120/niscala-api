"""create tenants, leases and invitations

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-18 00:00:08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("phone", sa.String(), nullable=False),
        sa.Column("occupation", sa.String(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_accounts.id"],
            name=op.f("fk_tenants_user_id_user_accounts"),
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_tenants")),
    )
    op.create_table(
        "emergency_contacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("relationship", sa.String(), nullable=False),
        sa.Column("phone", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.user_id"],
            name=op.f("fk_emergency_contacts_tenant_id_tenants"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_emergency_contacts")),
        sa.UniqueConstraint(
            "tenant_id", "position", name=op.f("uq_emergency_contacts_tenant_id")
        ),
    )
    op.create_table(
        "leases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("billing_cycle", sa.String(), nullable=False),
        sa.Column("rent", sa.Integer(), nullable=False),
        sa.Column("grace_period_days", sa.Integer(), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "billing_cycle IN ('weekly', 'monthly', 'quarterly', 'semiannual', "
            "'annual')",
            name=op.f("ck_leases_billing_cycle"),
        ),
        sa.CheckConstraint("rent > 0", name=op.f("ck_leases_rent_positive")),
        sa.CheckConstraint(
            "grace_period_days >= 0",
            name=op.f("ck_leases_grace_period_days_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["room_id"], ["rooms.id"], name=op.f("fk_leases_room_id_rooms")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.user_id"], name=op.f("fk_leases_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_leases")),
    )
    op.create_index(
        op.f("uq_leases_active_room"),
        "leases",
        ["room_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.create_index(
        op.f("uq_leases_active_tenant"),
        "leases",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.create_table(
        "invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("token_encrypted", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.user_id"],
            name=op.f("fk_invitations_tenant_id_tenants"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invitations")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_invitations_token_hash")),
    )


def downgrade() -> None:
    op.drop_table("invitations")
    op.drop_index(op.f("uq_leases_active_tenant"), table_name="leases")
    op.drop_index(op.f("uq_leases_active_room"), table_name="leases")
    op.drop_table("leases")
    op.drop_table("emergency_contacts")
    op.drop_table("tenants")
