"""create managers and let invitations belong to a manager

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-27 00:00:01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "managers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("nickname", sa.String(), nullable=True),
        sa.Column("phone", sa.String(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["user_accounts.id"],
            name=op.f("fk_managers_owner_id_user_accounts"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_accounts.id"],
            name=op.f("fk_managers_user_id_user_accounts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_managers")),
    )
    op.create_index(
        op.f("uq_managers_owner_user"),
        "managers",
        ["owner_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.alter_column("invitations", "tenant_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column("invitations", sa.Column("manager_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_invitations_manager_id_managers"),
        "invitations",
        "managers",
        ["manager_id"],
        ["id"],
    )
    op.create_check_constraint(
        op.f("ck_invitations_one_invitee"),
        "invitations",
        "(tenant_id IS NULL) <> (manager_id IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_invitations_one_invitee"), "invitations", type_="check")
    op.drop_constraint(
        op.f("fk_invitations_manager_id_managers"), "invitations", type_="foreignkey"
    )
    op.execute("DELETE FROM invitations WHERE tenant_id IS NULL")
    op.drop_column("invitations", "manager_id")
    op.alter_column("invitations", "tenant_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_index(op.f("uq_managers_owner_user"), table_name="managers")
    op.drop_table("managers")
