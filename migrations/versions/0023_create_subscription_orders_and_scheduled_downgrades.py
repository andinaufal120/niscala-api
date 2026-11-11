"""add billing details to subscriptions, create subscription orders and scheduled downgrades

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-11 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: str | Sequence[str] | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column(
            "billing_period", sa.String(), server_default="monthly", nullable=False
        ),
    )
    op.add_column(
        "subscriptions",
        sa.Column(
            "auto_renew", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )
    op.add_column(
        "subscriptions", sa.Column("purchase_token", sa.String(), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_subscriptions_billing_period"),
        "subscriptions",
        "billing_period IN ('monthly', 'yearly')",
    )
    op.create_unique_constraint(
        op.f("uq_subscriptions_purchase_token"), "subscriptions", ["purchase_token"]
    )

    op.create_table(
        "subscription_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("plan", sa.String(), nullable=False),
        sa.Column("billing_period", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("purchase_token", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "plan IN ('basic', 'pro')", name=op.f("ck_subscription_orders_plan")
        ),
        sa.CheckConstraint(
            "billing_period IN ('monthly', 'yearly')",
            name=op.f("ck_subscription_orders_billing_period"),
        ),
        sa.CheckConstraint(
            "status IN ('awaitingPayment', 'succeeded', 'failed', 'expired')",
            name=op.f("ck_subscription_orders_status"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["user_accounts.id"],
            name=op.f("fk_subscription_orders_owner_id_user_accounts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscription_orders")),
        sa.UniqueConstraint(
            "purchase_token", name=op.f("uq_subscription_orders_purchase_token")
        ),
    )

    op.create_table(
        "scheduled_downgrades",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("plan", sa.String(), nullable=False),
        sa.Column("kept_property_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("kept_room_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.CheckConstraint(
            "plan IN ('free', 'basic', 'pro')",
            name=op.f("ck_scheduled_downgrades_plan"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["user_accounts.id"],
            name=op.f("fk_scheduled_downgrades_owner_id_user_accounts"),
        ),
        sa.PrimaryKeyConstraint("owner_id", name=op.f("pk_scheduled_downgrades")),
    )


def downgrade() -> None:
    op.drop_table("scheduled_downgrades")
    op.drop_table("subscription_orders")
    op.drop_constraint(
        op.f("uq_subscriptions_purchase_token"), "subscriptions", type_="unique"
    )
    op.drop_constraint(
        op.f("ck_subscriptions_billing_period"), "subscriptions", type_="check"
    )
    op.drop_column("subscriptions", "purchase_token")
    op.drop_column("subscriptions", "auto_renew")
    op.drop_column("subscriptions", "billing_period")
