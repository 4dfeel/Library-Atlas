"""Add the download size the platform reports for a work."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("works", sa.Column("download_size", sa.Integer(), nullable=True))
