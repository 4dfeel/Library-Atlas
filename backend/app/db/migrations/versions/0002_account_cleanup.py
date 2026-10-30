"""Track unfinished session cleanup, so a disconnected account can never be restored."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_accounts",
        sa.Column("cleanup_pending", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
