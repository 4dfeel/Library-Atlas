"""Work folders found on the user's drives, and what they decided about them."""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scan_roots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("path_key", sa.String(), nullable=False, unique=True),
        sa.Column("active", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_scanned_at", sa.String(), nullable=True),
    )
    op.create_table(
        "scan_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("folders", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("found", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("skipped", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("complete", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("code", sa.String(), nullable=True),
        sa.Column("started_at", sa.String(), nullable=False),
        sa.Column("finished_at", sa.String(), nullable=True),
        sa.CheckConstraint(
            "state IN ('running', 'done', 'failed', 'cancelled', 'interrupted')",
            name="ck_scan_jobs_state",
        ),
    )
    op.create_table(
        "scan_items",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("root_id", sa.String(), sa.ForeignKey("scan_roots.id"), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("path_key", sa.String(), nullable=False, unique=True),
        sa.Column("kind_folder", sa.String(), nullable=False),
        sa.Column("maker", sa.String(), nullable=False),
        sa.Column("maker_key", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("title_key", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("candidates", sa.Text(), nullable=True),
        sa.Column("work_id", sa.String(), nullable=True),
        sa.Column("batch_id", sa.String(), nullable=True),
        sa.Column("job_id", sa.String(), nullable=True),
        sa.CheckConstraint(
            "state IN ('certain', 'likely', 'review', 'unmatched', 'linked', 'ignored')",
            name="ck_scan_items_state",
        ),
    )
    op.create_index("ix_scan_items_state", "scan_items", ["state", "maker_key", "title_key"])
    op.create_index("ix_scan_jobs_started", "scan_jobs", ["started_at"])
