"""Scans link what they match by themselves, and remember what the user took back."""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scan_jobs", sa.Column("auto_linked", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("scan_jobs", sa.Column("batch_id", sa.String(), nullable=True))
    op.add_column(
        "scan_items", sa.Column("declined", sa.Integer(), nullable=False, server_default="0")
    )
