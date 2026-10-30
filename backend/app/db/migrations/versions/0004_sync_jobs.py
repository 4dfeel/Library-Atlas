"""Add sync jobs, the last complete sync time and a work's address on the platform."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sync_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=True),
        sa.Column("processed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("added", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("skipped", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("missing", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("started_at", sa.String(), nullable=False),
        sa.Column("finished_at", sa.String(), nullable=True),
        sa.CheckConstraint(
            "state IN ('preparing', 'reading', 'saving', 'succeeded', 'partial', 'failed', "
            "'cancelled', 'reauth_required', 'interrupted')",
            name="ck_sync_jobs_state",
        ),
    )
    op.create_index("ix_sync_jobs_started", "sync_jobs", ["started_at"])
    op.add_column("source_accounts", sa.Column("last_synced_at", sa.String(), nullable=True))
    op.add_column("works", sa.Column("source_url", sa.String(), nullable=True))
