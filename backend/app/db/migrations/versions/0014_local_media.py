"""Where the user got to in local media, their bookmarks and playlists."""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_progress",
        sa.Column("resource_id", sa.String(), primary_key=True),
        sa.Column("work_id", sa.String(), sa.ForeignKey("works.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("position", sa.Float(), nullable=False),
        sa.Column("total", sa.Float(), nullable=True),
        sa.Column("stamp", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index("ix_media_progress_work", "media_progress", ["work_id", "kind"])
    op.create_table(
        "media_bookmarks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("work_id", sa.String(), sa.ForeignKey("works.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("resource_id", sa.String(), nullable=False),
        sa.Column("position", sa.Float(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("stamp", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_media_bookmarks_work", "media_bookmarks", ["work_id", "kind"])
    op.create_table(
        "playlists",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_table(
        "playlist_items",
        sa.Column("playlist_id", sa.String(), sa.ForeignKey("playlists.id"), primary_key=True),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("copy_id", sa.String(), nullable=False),
        sa.Column("track_id", sa.String(), nullable=False),
        sa.Column("work_id", sa.String(), sa.ForeignKey("works.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
    )
