"""Remember which archives were removed after unpacking, and what the user cleared from view."""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in ("archive_removed", "dismissed"):
        op.add_column(
            "download_tasks",
            sa.Column(column, sa.Integer(), nullable=False, server_default=sa.text("0")),
        )
    op.add_column(
        "extract_tasks",
        sa.Column("dismissed", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
