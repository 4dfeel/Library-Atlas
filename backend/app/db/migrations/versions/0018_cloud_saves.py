"""What each Google account's copy of a work's saves was last agreed to be, and what waits to go up."""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cloud_states",
        sa.Column("account_id", sa.String(), primary_key=True),
        sa.Column("work_id", sa.String(), sa.ForeignKey("works.id"), primary_key=True),
        sa.Column("base_snapshot", sa.String(), nullable=True),
        sa.Column("base_digest", sa.String(), nullable=True),
        sa.Column("restoring", sa.String(), nullable=True),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_table(
        "cloud_outbox",
        sa.Column("snapshot_id", sa.String(), primary_key=True),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("work_id", sa.String(), sa.ForeignKey("works.id"), nullable=False),
        sa.Column("source_work_id", sa.String(), nullable=False),
        sa.Column("digest", sa.String(), nullable=False),
        sa.Column("manifest", sa.Text(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_cloud_outbox_work", "cloud_outbox", ["account_id", "work_id"])
