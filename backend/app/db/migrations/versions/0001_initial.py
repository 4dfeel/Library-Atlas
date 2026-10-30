"""Initial library schema: sources, accounts, works, files, entries, personal records."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "library_meta",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("value", sa.String(), nullable=False),
    )
    sources = op.create_table(
        "sources",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.CheckConstraint("id IN ('steam', 'dlsite')", name="ck_sources_id"),
    )
    op.bulk_insert(
        sources,
        [{"id": "steam", "display_name": "Steam"}, {"id": "dlsite", "display_name": "DLsite"}],
    )
    op.create_table(
        "source_accounts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source_id", sa.String(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("credential_ref", sa.String(), nullable=True),
        sa.Column("account_fingerprint", sa.String(), nullable=True),
        sa.Column("state", sa.String(), nullable=False, server_default="not_connected"),
        sa.Column("last_verified_at", sa.String(), nullable=True),
        sa.CheckConstraint(
            "state IN ('not_connected', 'connected', 'reauth_required', 'error')",
            name="ck_source_accounts_state",
        ),
        sa.UniqueConstraint("source_id", "account_fingerprint", name="uq_source_accounts_identity"),
    )
    op.create_table(
        "works",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source_id", sa.String(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("source_work_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False, server_default="other"),
        sa.Column("raw_kind", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("subtitle", sa.String(), nullable=True),
        sa.Column("maker", sa.String(), nullable=True),
        sa.Column("genre", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("release_date", sa.String(), nullable=True),
        sa.Column("cover_ref", sa.String(), nullable=True),
        sa.Column("backdrop_ref", sa.String(), nullable=True),
        sa.Column("tags_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("playtime_minutes", sa.Integer(), nullable=True),
        sa.Column("last_used_at", sa.String(), nullable=True),
        sa.Column("achievements_unlocked", sa.Integer(), nullable=True),
        sa.Column("achievements_total", sa.Integer(), nullable=True),
        sa.Column("local_state", sa.String(), nullable=False, server_default="unknown"),
        sa.Column("can_download", sa.Integer(), nullable=True),
        sa.Column("can_extract", sa.Integer(), nullable=True),
        sa.Column("official_viewer_only", sa.Integer(), nullable=True),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("sort_title", sa.Text(), nullable=False),
        sa.Column("metadata_updated_at", sa.String(), nullable=False),
        sa.UniqueConstraint("source_id", "source_work_id", name="uq_works_source_identity"),
        sa.CheckConstraint(
            "kind IN ('game', 'image', 'video', 'audio', 'other')", name="ck_works_kind"
        ),
        sa.CheckConstraint(
            "local_state IN ('unknown', 'available', 'absent')", name="ck_works_local"
        ),
        sa.CheckConstraint(
            "playtime_minutes IS NULL OR playtime_minutes >= 0", name="ck_works_playtime"
        ),
        sa.CheckConstraint(
            "(achievements_total IS NULL AND achievements_unlocked IS NULL) OR "
            "(achievements_total >= 0 AND achievements_unlocked BETWEEN 0 AND achievements_total)",
            name="ck_works_achievements",
        ),
    )
    op.create_index("ix_works_sort_title", "works", ["sort_title", "id"])
    op.create_index("ix_works_kind_source", "works", ["kind", "source_id"])
    op.create_table(
        "work_files",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("work_id", sa.String(), sa.ForeignKey("works.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("version", sa.String(), nullable=True),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("part_index", sa.Integer(), nullable=True),
        sa.Column("part_count", sa.Integer(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("format", sa.String(), nullable=True),
        sa.Column("availability", sa.String(), nullable=False, server_default="unknown"),
        sa.Column("download_state", sa.String(), nullable=False, server_default="unknown"),
        sa.Column("extract_state", sa.String(), nullable=False, server_default="unknown"),
        sa.CheckConstraint(
            "availability IN ('unknown', 'downloadable', 'viewer_only')",
            name="ck_files_availability",
        ),
        sa.CheckConstraint(
            "download_state IN ('unknown', 'not_downloaded', 'downloaded')",
            name="ck_files_download",
        ),
        sa.CheckConstraint(
            "extract_state IN ('unknown', 'not_applicable', 'not_extracted', 'extracted')",
            name="ck_files_extract",
        ),
        sa.CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="ck_files_size"),
    )
    op.create_index("ix_work_files_work", "work_files", ["work_id", "position"])
    op.create_table(
        "library_entries",
        sa.Column("work_id", sa.String(), sa.ForeignKey("works.id"), primary_key=True),
        sa.Column(
            "source_account_id", sa.String(), sa.ForeignKey("source_accounts.id"), nullable=True
        ),
        sa.Column("ownership_status", sa.String(), nullable=False, server_default="unknown"),
        sa.Column("added_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            "ownership_status IN ('unknown', 'observed_owned', 'not_currently_observed')",
            name="ck_entries_ownership",
        ),
    )
    op.create_index("ix_entries_added", "library_entries", ["added_at", "work_id"])
    op.create_table(
        "personal_records",
        sa.Column("work_id", sa.String(), sa.ForeignKey("works.id"), primary_key=True),
        sa.Column("visibility", sa.String(), nullable=False, server_default="quarantined"),
        sa.Column("status", sa.String(), nullable=False, server_default="unplayed"),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("favorite", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            "visibility IN ('normal', 'hidden', 'private', 'quarantined')",
            name="ck_personal_visibility",
        ),
        sa.CheckConstraint(
            "status IN ('unplayed', 'playing', 'completed', 'paused')", name="ck_personal_status"
        ),
        sa.CheckConstraint("rating IS NULL OR rating BETWEEN 1 AND 5", name="ck_personal_rating"),
        sa.CheckConstraint("length(note) <= 1000", name="ck_personal_note"),
        sa.CheckConstraint("favorite IN (0, 1)", name="ck_personal_favorite"),
    )
    op.create_index("ix_personal_visibility", "personal_records", ["visibility", "work_id"])
