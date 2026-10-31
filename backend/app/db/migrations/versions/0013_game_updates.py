"""Save locations, save backups, and game updates in progress."""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "save_configs",
        sa.Column("work_id", sa.String(), sa.ForeignKey("works.id"), primary_key=True),
        sa.Column("rules", sa.Text(), nullable=False),
        sa.Column("confirmed_none", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_table(
        "save_backups",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("work_id", sa.String(), sa.ForeignKey("works.id"), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("rules", sa.Text(), nullable=False),
        sa.Column("manifest", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_save_backups_work", "save_backups", ["work_id", "created_at"])
    op.create_table(
        "game_updates",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("work_id", sa.String(), sa.ForeignKey("works.id"), nullable=False),
        sa.Column("copy_id", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("active_key", sa.String(), nullable=True, unique=True),
        sa.Column("root_path", sa.String(), nullable=False),
        sa.Column("staging_path", sa.String(), nullable=True),
        sa.Column("old_path", sa.String(), nullable=True),
        sa.Column("backup_id", sa.String(), nullable=True),
        sa.Column("source_task_ids", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("extra_count", sa.Integer(), nullable=True),
        sa.Column("extra_sample", sa.Text(), nullable=True),
        sa.Column("cleanup_failed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("finished_at", sa.String(), nullable=True),
        sa.CheckConstraint(
            "state IN ('queued', 'backing_up', 'downloading', 'unpacking', 'replacing', "
            "'awaiting_confirmation', 'cleaning', 'done', 'failed', 'cancelled', 'interrupted', "
            "'rolled_back')",
            name="ck_game_updates_state",
        ),
    )
    op.create_index("ix_game_updates_work", "game_updates", ["work_id", "created_at"])
