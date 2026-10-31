"""Each time a game was played, and for how long, marked with where the figure came from."""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "play_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("work_id", sa.String(), sa.ForeignKey("works.id"), nullable=False),
        sa.Column("copy_id", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("started_at", sa.String(), nullable=False),
        sa.Column("heartbeat_at", sa.String(), nullable=False),
        sa.Column("ended_at", sa.String(), nullable=True),
        sa.Column("ended_by", sa.String(), nullable=True),
        sa.Column("seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("watch_name", sa.String(), nullable=True),
    )
    op.create_index("ix_play_sessions_work", "play_sessions", ["work_id", "started_at"])
    op.create_index("ix_play_sessions_state", "play_sessions", ["state"])
