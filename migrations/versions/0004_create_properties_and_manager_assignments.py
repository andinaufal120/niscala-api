"""create properties and manager assignments

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-18 00:00:03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "properties",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("address", sa.String(), nullable=False),
        sa.Column("view_only", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["user_accounts.id"],
            name=op.f("fk_properties_owner_id_user_accounts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_properties")),
    )
    op.create_table(
        "manager_assignments",
        sa.Column("manager_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["manager_id"],
            ["user_accounts.id"],
            name=op.f("fk_manager_assignments_manager_id_user_accounts"),
        ),
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
            name=op.f("fk_manager_assignments_property_id_properties"),
        ),
        sa.PrimaryKeyConstraint(
            "manager_id", "property_id", name=op.f("pk_manager_assignments")
        ),
    )


def downgrade() -> None:
    op.drop_table("manager_assignments")
    op.drop_table("properties")
