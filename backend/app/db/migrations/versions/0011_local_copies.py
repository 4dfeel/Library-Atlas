"""Where a work's files are on this computer."""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "local_copies",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("work_id", sa.String(), sa.ForeignKey("works.id"), nullable=False),
        sa.Column("root_path", sa.String(), nullable=False),
        sa.Column("root_key", sa.String(), nullable=False),
        sa.Column("entry_path", sa.String(), nullable=True),
        sa.Column("working_path", sa.String(), nullable=True),
        sa.Column("arguments", sa.JSON(), nullable=True),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("is_default", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("batch_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.UniqueConstraint("work_id", "root_key", name="uq_local_copies_work_root"),
        sa.CheckConstraint(
            "origin IN ('manual', 'unpacked', 'scanned')", name="ck_local_copies_origin"
        ),
    )
    op.create_index("ix_local_copies_work", "local_copies", ["work_id", "is_default"])
