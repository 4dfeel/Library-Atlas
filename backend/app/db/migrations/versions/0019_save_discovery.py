"""A session of play being watched, to see where a game writes its saves."""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "save_discoveries",
        sa.Column("work_id", sa.String(), sa.ForeignKey("works.id"), primary_key=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("started_at", sa.String(), nullable=True),
        sa.Column("started_clock", sa.Float(), nullable=True),
        sa.Column("finished_at", sa.String(), nullable=True),
        sa.Column("results", sa.Text(), nullable=True),
        sa.Column("complete", sa.Integer(), nullable=False, server_default="1"),
    )
