"""Remember when a work last changed on the platform, and its store images."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("works", sa.Column("upgraded_at", sa.String(), nullable=True))
    op.add_column("works", sa.Column("gallery_json", sa.Text(), nullable=True))
    op.add_column("works", sa.Column("gallery_checked_at", sa.String(), nullable=True))
    op.add_column("download_tasks", sa.Column("source_upgraded_at", sa.String(), nullable=True))
