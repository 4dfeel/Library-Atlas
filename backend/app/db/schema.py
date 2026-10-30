"""Atlas-owned tables. Source metadata and personal records are deliberately separate:
sync code writes `works`, `work_files` and `library_entries`; only explicit user actions
write `personal_records`. One database is one library; account isolation comes from one
database per profile directory.
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)

metadata = MetaData()

library_meta = Table(
    "library_meta",
    metadata,
    Column("key", String, primary_key=True),
    Column("value", String, nullable=False),
)

app_settings = Table(
    "app_settings",
    metadata,
    Column("key", String, primary_key=True),
    Column("value", String, nullable=False),
)

sources = Table(
    "sources",
    metadata,
    Column("id", String, primary_key=True),
    Column("display_name", String, nullable=False),
    CheckConstraint("id IN ('steam', 'dlsite')", name="ck_sources_id"),
)

source_accounts = Table(
    "source_accounts",
    metadata,
    Column("id", String, primary_key=True),
    Column("source_id", String, ForeignKey("sources.id"), nullable=False),
    # Name of a credential-store entry, never the secret itself.
    Column("credential_ref", String, nullable=True),
    # Hash of the platform's account identity, never the identity itself.
    Column("account_fingerprint", String, nullable=True),
    # Masked for display, such as a14•••@example.com. Never the full name.
    Column("account_alias", String, nullable=True),
    Column("state", String, nullable=False, server_default="not_connected"),
    Column("last_verified_at", String, nullable=True),
    # Set before a stored session is deleted and cleared after. While set, the session is
    # never read, so a failed cleanup cannot bring a disconnected account back.
    Column("cleanup_pending", Integer, nullable=False, server_default=text("0")),
    # Set only by a complete sync. An attempt's own time lives on its sync_jobs row.
    Column("last_synced_at", String, nullable=True),
    CheckConstraint(
        "state IN ('not_connected', 'connected', 'reauth_required', 'error')",
        name="ck_source_accounts_state",
    ),
    UniqueConstraint("source_id", "account_fingerprint", name="uq_source_accounts_identity"),
)

works = Table(
    "works",
    metadata,
    Column("id", String, primary_key=True),
    Column("source_id", String, ForeignKey("sources.id"), nullable=False),
    Column("source_work_id", String, nullable=False),
    Column("kind", String, nullable=False, server_default="other"),
    # The platform's own type code, kept so a wrong mapping can be diagnosed and redone.
    Column("raw_kind", String, nullable=True),
    Column("title", String, nullable=False),
    Column("subtitle", String, nullable=True),
    Column("maker", String, nullable=True),
    Column("genre", String, nullable=True),
    Column("description", Text, nullable=True),
    Column("release_date", String, nullable=True),
    Column("cover_ref", String, nullable=True),
    Column("backdrop_ref", String, nullable=True),
    Column("tags_json", Text, nullable=False, server_default="[]"),
    # NULL means not reported, which is never the same as 0.
    Column("playtime_minutes", Integer, nullable=True),
    Column("last_used_at", String, nullable=True),
    Column("achievements_unlocked", Integer, nullable=True),
    Column("achievements_total", Integer, nullable=True),
    # Available locally: installed for Steam, downloaded for DLsite. Extraction and
    # launchability are separate facts and live on work_files or later checkpoints.
    Column("local_state", String, nullable=False, server_default="unknown"),
    Column("can_download", Integer, nullable=True),
    Column("can_extract", Integer, nullable=True),
    Column("official_viewer_only", Integer, nullable=True),
    Column("search_text", Text, nullable=False),
    Column("sort_title", Text, nullable=False),
    Column("metadata_updated_at", String, nullable=False),
    Column("source_url", String, nullable=True),
    # As the platform reports it. NULL means not reported, never an empty download.
    Column("download_size", Integer, nullable=True),
    UniqueConstraint("source_id", "source_work_id", name="uq_works_source_identity"),
    CheckConstraint("kind IN ('game', 'image', 'video', 'audio', 'other')", name="ck_works_kind"),
    CheckConstraint("local_state IN ('unknown', 'available', 'absent')", name="ck_works_local"),
    CheckConstraint("playtime_minutes IS NULL OR playtime_minutes >= 0", name="ck_works_playtime"),
    CheckConstraint(
        "(achievements_total IS NULL AND achievements_unlocked IS NULL) OR "
        "(achievements_total >= 0 AND achievements_unlocked BETWEEN 0 AND achievements_total)",
        name="ck_works_achievements",
    ),
    Index("ix_works_sort_title", "sort_title", "id"),
    Index("ix_works_kind_source", "kind", "source_id"),
)

work_files = Table(
    "work_files",
    metadata,
    Column("id", String, primary_key=True),
    Column("work_id", String, ForeignKey("works.id"), nullable=False),
    Column("position", Integer, nullable=False, server_default="0"),
    Column("label", String, nullable=True),
    Column("version", String, nullable=True),
    Column("language", String, nullable=True),
    Column("part_index", Integer, nullable=True),
    Column("part_count", Integer, nullable=True),
    Column("size_bytes", Integer, nullable=True),
    Column("format", String, nullable=True),
    Column("availability", String, nullable=False, server_default="unknown"),
    Column("download_state", String, nullable=False, server_default="unknown"),
    Column("extract_state", String, nullable=False, server_default="unknown"),
    CheckConstraint(
        "availability IN ('unknown', 'downloadable', 'viewer_only')", name="ck_files_availability"
    ),
    CheckConstraint(
        "download_state IN ('unknown', 'not_downloaded', 'downloaded')", name="ck_files_download"
    ),
    CheckConstraint(
        "extract_state IN ('unknown', 'not_applicable', 'not_extracted', 'extracted')",
        name="ck_files_extract",
    ),
    CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="ck_files_size"),
    Index("ix_work_files_work", "work_id", "position"),
)

sync_jobs = Table(
    "sync_jobs",
    metadata,
    Column("id", String, primary_key=True),
    Column("state", String, nullable=False),
    Column("total", Integer, nullable=True),
    Column("processed", Integer, nullable=False, server_default=text("0")),
    Column("added", Integer, nullable=False, server_default=text("0")),
    Column("updated", Integer, nullable=False, server_default=text("0")),
    Column("skipped", Integer, nullable=False, server_default=text("0")),
    Column("missing", Integer, nullable=False, server_default=text("0")),
    Column("error_code", String, nullable=True),
    Column("started_at", String, nullable=False),
    Column("finished_at", String, nullable=True),
    CheckConstraint(
        "state IN ('preparing', 'reading', 'saving', 'succeeded', 'partial', 'failed', "
        "'cancelled', 'reauth_required', 'interrupted')",
        name="ck_sync_jobs_state",
    ),
    Index("ix_sync_jobs_started", "started_at"),
)

library_entries = Table(
    "library_entries",
    metadata,
    Column("work_id", String, ForeignKey("works.id"), primary_key=True),
    Column("source_account_id", String, ForeignKey("source_accounts.id"), nullable=True),
    Column("ownership_status", String, nullable=False, server_default="unknown"),
    Column("added_at", String, nullable=False),
    CheckConstraint(
        "ownership_status IN ('unknown', 'observed_owned', 'not_currently_observed')",
        name="ck_entries_ownership",
    ),
    Index("ix_entries_added", "added_at", "work_id"),
)

personal_records = Table(
    "personal_records",
    metadata,
    Column("work_id", String, ForeignKey("works.id"), primary_key=True),
    # New works stay out of ordinary views until the user confirms them.
    Column("visibility", String, nullable=False, server_default="quarantined"),
    Column("status", String, nullable=False, server_default="unplayed"),
    Column("rating", Integer, nullable=True),
    Column("note", Text, nullable=False, server_default=""),
    Column("favorite", Integer, nullable=False, server_default=text("0")),
    Column("version", Integer, nullable=False, server_default=text("1")),
    Column("updated_at", String, nullable=False),
    CheckConstraint(
        "visibility IN ('normal', 'hidden', 'private', 'quarantined')",
        name="ck_personal_visibility",
    ),
    CheckConstraint(
        "status IN ('unplayed', 'playing', 'completed', 'paused')", name="ck_personal_status"
    ),
    CheckConstraint("rating IS NULL OR rating BETWEEN 1 AND 5", name="ck_personal_rating"),
    CheckConstraint("length(note) <= 1000", name="ck_personal_note"),
    CheckConstraint("favorite IN (0, 1)", name="ck_personal_favorite"),
    Index("ix_personal_visibility", "visibility", "work_id"),
)
