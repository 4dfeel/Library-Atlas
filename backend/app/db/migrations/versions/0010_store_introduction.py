"""Keep the store's full introduction for each work once it has been read."""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("works", sa.Column("intro_json", sa.Text(), nullable=True))
    op.add_column("works", sa.Column("intro_fetched_at", sa.String(), nullable=True))
