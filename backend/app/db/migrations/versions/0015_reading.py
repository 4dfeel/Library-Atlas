"""How far the user has read each book, and their bookmarks in it."""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reading_progress",
        sa.Column("book_id", sa.String(), primary_key=True),
        sa.Column("work_id", sa.String(), sa.ForeignKey("works.id"), nullable=False),
        sa.Column("page_id", sa.String(), nullable=True),
        sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("read_state", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index("ix_reading_progress_work", "reading_progress", ["work_id"])
    op.create_table(
        "reader_bookmarks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("work_id", sa.String(), sa.ForeignKey("works.id"), nullable=False),
        sa.Column("book_id", sa.String(), nullable=False),
        sa.Column("page_id", sa.String(), nullable=False),
        sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_reader_bookmarks_book", "reader_bookmarks", ["book_id"])
