"""create rooms

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-18 00:00:07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rooms",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(), nullable=False),
        sa.Column("base_rate", sa.Integer(), nullable=False),
        sa.Column("length_m", sa.Numeric(4, 2), nullable=True),
        sa.Column("width_m", sa.Numeric(4, 2), nullable=True),
        sa.Column("facilities", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("view_only", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("base_rate > 0", name=op.f("ck_rooms_base_rate_positive")),
        sa.CheckConstraint(
            "length_m IS NULL OR length_m > 0", name=op.f("ck_rooms_length_m_positive")
        ),
        sa.CheckConstraint(
            "width_m IS NULL OR width_m > 0", name=op.f("ck_rooms_width_m_positive")
        ),
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
            name=op.f("fk_rooms_property_id_properties"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rooms")),
    )
    op.create_index(
        op.f("uq_rooms_property_number"),
        "rooms",
        ["property_id", sa.text("lower(number)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(op.f("uq_rooms_property_number"), table_name="rooms")
    op.drop_table("rooms")
