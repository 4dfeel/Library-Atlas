"""The user's own named collections of works."""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "collections",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("name_key", sa.String(), nullable=False, unique=True),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_table(
        "collection_items",
        sa.Column("collection_id", sa.String(), sa.ForeignKey("collections.id"), primary_key=True),
        sa.Column("work_id", sa.String(), sa.ForeignKey("works.id"), primary_key=True),
        sa.Column("added_at", sa.String(), nullable=False),
    )
    op.create_index("ix_collection_items_work", "collection_items", ["work_id"])
