"""give a tenant record an id of its own so an account can hold several

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-09 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | Sequence[str] | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEPENDENTS = ("emergency_contacts", "leases", "invitations", "complaints")


def _drop_foreign_keys() -> None:
    for table in DEPENDENTS:
        op.drop_constraint(
            op.f(f"fk_{table}_tenant_id_tenants"), table, type_="foreignkey"
        )


def _create_foreign_keys(column: str) -> None:
    for table in DEPENDENTS:
        op.create_foreign_key(
            op.f(f"fk_{table}_tenant_id_tenants"),
            table,
            "tenants",
            ["tenant_id"],
            [column],
        )


def upgrade() -> None:
    _drop_foreign_keys()
    op.add_column("tenants", sa.Column("id", sa.Uuid(), nullable=True))
    op.execute("UPDATE tenants SET id = user_id")
    op.alter_column("tenants", "id", existing_type=sa.Uuid(), nullable=False)
    op.drop_constraint(op.f("pk_tenants"), "tenants", type_="primary")
    op.create_primary_key(op.f("pk_tenants"), "tenants", ["id"])
    _create_foreign_keys("id")
    op.create_index(op.f("ix_tenants_user_id"), "tenants", ["user_id"])


def downgrade() -> None:
    # Only the oldest record of an account survives. The leases and complaints
    # of the others move to it (the leases ended, so each record keeps at most
    # one active lease); their contacts and invitations are deleted.
    op.execute(
        "CREATE TEMPORARY TABLE tenant_keepers AS "
        "SELECT id, first_value(id) OVER ("
        "PARTITION BY user_id ORDER BY created_at, id) AS keep_id FROM tenants"
    )
    op.execute("DELETE FROM tenant_keepers WHERE id = keep_id")
    _drop_foreign_keys()
    op.execute(
        "UPDATE leases SET tenant_id = tenant_keepers.keep_id, "
        "ended_at = COALESCE(leases.ended_at, now()) "
        "FROM tenant_keepers WHERE leases.tenant_id = tenant_keepers.id"
    )
    op.execute(
        "UPDATE complaints SET tenant_id = tenant_keepers.keep_id "
        "FROM tenant_keepers WHERE complaints.tenant_id = tenant_keepers.id"
    )
    for table in ("emergency_contacts", "invitations"):
        op.execute(
            f"DELETE FROM {table} USING tenant_keepers "
            f"WHERE {table}.tenant_id = tenant_keepers.id"
        )
    op.execute(
        "DELETE FROM tenants USING tenant_keepers WHERE tenants.id = tenant_keepers.id"
    )
    op.execute("DROP TABLE tenant_keepers")
    op.drop_index(op.f("ix_tenants_user_id"), table_name="tenants")
    op.drop_constraint(op.f("pk_tenants"), "tenants", type_="primary")
    op.drop_column("tenants", "id")
    op.create_primary_key(op.f("pk_tenants"), "tenants", ["user_id"])
    _create_foreign_keys("user_id")
