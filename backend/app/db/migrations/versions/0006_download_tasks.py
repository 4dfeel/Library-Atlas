"""Add persistent download tasks."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "download_tasks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("work_id", sa.String(), sa.ForeignKey("works.id"), nullable=False),
        sa.Column("part_number", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("part_count", sa.Integer(), nullable=True),
        sa.Column("account_fingerprint", sa.String(), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("active_key", sa.String(), nullable=True, unique=True),
        sa.Column("target_dir", sa.String(), nullable=False),
        sa.Column("cache_dir", sa.String(), nullable=False),
        sa.Column("file_name", sa.String(), nullable=True),
        sa.Column("bytes_done", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("bytes_total", sa.Integer(), nullable=True),
        sa.Column("etag", sa.String(), nullable=True),
        sa.Column("last_modified", sa.String(), nullable=True),
        sa.Column("sha256", sa.String(), nullable=True),
        sa.Column("integrity", sa.String(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("finished_at", sa.String(), nullable=True),
        sa.CheckConstraint(
            "state IN ('queued', 'resolving', 'downloading', 'verifying', 'paused', 'done', "
            "'failed', 'cancelled', 'reauth_required', 'interrupted')",
            name="ck_download_tasks_state",
        ),
    )
    op.create_index("ix_download_tasks_work", "download_tasks", ["work_id", "part_number"])
    op.create_index("ix_download_tasks_state", "download_tasks", ["state", "created_at"])
