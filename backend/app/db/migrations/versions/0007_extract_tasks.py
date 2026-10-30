"""Add unpacking tasks, and tie downloads to the user's wish to unpack them."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "extract_tasks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("work_id", sa.String(), sa.ForeignKey("works.id"), nullable=False),
        sa.Column("source_work_id", sa.String(), nullable=False),
        sa.Column("account_fingerprint", sa.String(), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("active_key", sa.String(), nullable=True, unique=True),
        sa.Column("source_task_ids", sa.Text(), nullable=False),
        sa.Column("root_dir", sa.String(), nullable=False),
        sa.Column("final_name", sa.String(), nullable=True),
        sa.Column("format", sa.String(), nullable=True),
        sa.Column("files_total", sa.Integer(), nullable=True),
        sa.Column("bytes_total", sa.Integer(), nullable=True),
        sa.Column("bytes_done", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("cleanup_failed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("finished_at", sa.String(), nullable=True),
        sa.CheckConstraint(
            "state IN ('queued', 'checking', 'extracting', 'committing', 'done', 'not_needed', "
            "'failed', 'cancelled', 'interrupted')",
            name="ck_extract_tasks_state",
        ),
    )
    op.create_index("ix_extract_tasks_work", "extract_tasks", ["work_id", "created_at"])
    op.create_index("ix_extract_tasks_state", "extract_tasks", ["state", "created_at"])
    op.add_column("download_tasks", sa.Column("flow_id", sa.String(), nullable=True))
