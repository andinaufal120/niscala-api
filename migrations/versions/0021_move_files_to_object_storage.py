"""Keep receipts and complaint photos in object storage.

Existing rows are deleted: their bytes have no object to point to.

Revision ID: 0021
Revises: 0020
"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

TABLES = ("rent_bill_receipts", "complaint_photos")


def upgrade() -> None:
    for table in TABLES:
        op.execute(sa.text(f"DELETE FROM {table}"))
        op.drop_column(table, "content")
        op.add_column(table, sa.Column("storage_key", sa.String(), nullable=False))
        op.create_unique_constraint(
            op.f(f"uq_{table}_storage_key"), table, ["storage_key"]
        )


def downgrade() -> None:
    for table in TABLES:
        op.execute(sa.text(f"DELETE FROM {table}"))
        op.drop_constraint(op.f(f"uq_{table}_storage_key"), table, type_="unique")
        op.drop_column(table, "storage_key")
        op.add_column(table, sa.Column("content", sa.LargeBinary(), nullable=False))
