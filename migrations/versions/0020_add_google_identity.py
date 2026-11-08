"""Add the Google identity columns to user_accounts.

Revision ID: 0020
Revises: 0019
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_accounts", sa.Column("google_subject", sa.String()))
    op.add_column("user_accounts", sa.Column("google_email", sa.String()))
    op.create_unique_constraint(
        op.f("uq_user_accounts_google_subject"), "user_accounts", ["google_subject"]
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("uq_user_accounts_google_subject"), "user_accounts", type_="unique"
    )
    op.drop_column("user_accounts", "google_email")
    op.drop_column("user_accounts", "google_subject")
