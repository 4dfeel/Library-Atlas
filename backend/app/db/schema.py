"""Atlas-owned tables. Source metadata and personal records are deliberately separate:
sync code writes `works`, `work_files` and `library_entries`; only explicit user actions
write `personal_records`. One database is one library; account isolation comes from one
database per profile directory.
"""

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    Float,
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
    # As the platform reports it; only ever compared with an earlier value of itself.
    Column("upgraded_at", String, nullable=True),
    Column("gallery_json", Text, nullable=True),
    Column("gallery_checked_at", String, nullable=True),
    # Checked blocks, never HTML. Separate from `description`, the short summary.
    Column("intro_json", Text, nullable=True),
    Column("intro_fetched_at", String, nullable=True),
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

download_tasks = Table(
    "download_tasks",
    metadata,
    Column("id", String, primary_key=True),
    Column("work_id", String, ForeignKey("works.id"), nullable=False),
    # 0 for a work delivered as one file; otherwise the platform's part number.
    Column("part_number", Integer, nullable=False, server_default=text("0")),
    Column("part_count", Integer, nullable=True),
    Column("account_fingerprint", String, nullable=True),
    Column("state", String, nullable=False),
    Column("attempt", Integer, nullable=False, server_default=text("1")),
    # Set while a task is live, so the database refuses a second one for the same file.
    Column("active_key", String, nullable=True, unique=True),
    # Fixed when the task is created: changing a folder later does not move this task.
    Column("target_dir", String, nullable=False),
    Column("cache_dir", String, nullable=False),
    Column("file_name", String, nullable=True),
    Column("bytes_done", Integer, nullable=False, server_default=text("0")),
    Column("bytes_total", Integer, nullable=True),
    Column("etag", String, nullable=True),
    Column("last_modified", String, nullable=True),
    Column("sha256", String, nullable=True),
    Column("integrity", String, nullable=True),
    Column("error_code", String, nullable=True),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
    Column("finished_at", String, nullable=True),
    # Set when the user asked to unpack: its files move on together once all are done.
    Column("flow_id", String, nullable=True),
    # The work's change date when this was downloaded, to notice a newer version.
    Column("source_upgraded_at", String, nullable=True),
    # The archive served its purpose and was deleted: not the same as a file gone missing.
    Column("archive_removed", Integer, nullable=False, server_default=text("0")),
    # Cleared from the list by the user. The record stays: it is how updates are noticed.
    Column("dismissed", Integer, nullable=False, server_default=text("0")),
    CheckConstraint(
        "state IN ('queued', 'resolving', 'downloading', 'verifying', 'paused', 'done', "
        "'failed', 'cancelled', 'reauth_required', 'interrupted')",
        name="ck_download_tasks_state",
    ),
    Index("ix_download_tasks_work", "work_id", "part_number"),
    Index("ix_download_tasks_state", "state", "created_at"),
)

extract_tasks = Table(
    "extract_tasks",
    metadata,
    Column("id", String, primary_key=True),
    Column("work_id", String, ForeignKey("works.id"), nullable=False),
    Column("source_work_id", String, nullable=False),
    Column("account_fingerprint", String, nullable=True),
    Column("state", String, nullable=False),
    Column("attempt", Integer, nullable=False, server_default=text("1")),
    Column("active_key", String, nullable=True, unique=True),
    # Which finished downloads this unpacks. Never a path, and never from a request.
    Column("source_task_ids", Text, nullable=False),
    Column("root_dir", String, nullable=False),
    Column("final_name", String, nullable=True),
    Column("format", String, nullable=True),
    Column("files_total", Integer, nullable=True),
    Column("bytes_total", Integer, nullable=True),
    Column("bytes_done", Integer, nullable=False, server_default=text("0")),
    Column("error_code", String, nullable=True),
    Column("cleanup_failed", Integer, nullable=False, server_default=text("0")),
    Column("dismissed", Integer, nullable=False, server_default=text("0")),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
    Column("finished_at", String, nullable=True),
    CheckConstraint(
        "state IN ('queued', 'checking', 'extracting', 'committing', 'done', 'not_needed', "
        "'failed', 'cancelled', 'interrupted')",
        name="ck_extract_tasks_state",
    ),
    Index("ix_extract_tasks_work", "work_id", "created_at"),
    Index("ix_extract_tasks_state", "state", "created_at"),
)

local_copies = Table(
    "local_copies",
    metadata,
    Column("id", String, primary_key=True),
    Column("work_id", String, ForeignKey("works.id"), nullable=False),
    Column("root_path", String, nullable=False),
    Column("root_key", String, nullable=False),  # Windows folder names ignore case.
    Column("entry_path", String, nullable=True),
    Column("working_path", String, nullable=True),
    Column("arguments", JSON, nullable=True),
    Column("label", String, nullable=True),
    Column("is_default", Integer, nullable=False, server_default=text("0")),
    Column("origin", String, nullable=False),
    Column("batch_id", String, nullable=True),  # The import that made it, so it can be undone.
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
    UniqueConstraint("work_id", "root_key", name="uq_local_copies_work_root"),
    CheckConstraint("origin IN ('manual', 'unpacked', 'scanned')", name="ck_local_copies_origin"),
    Index("ix_local_copies_work", "work_id", "is_default"),
)

scan_roots = Table(
    "scan_roots",
    metadata,
    Column("id", String, primary_key=True),
    Column("path", String, nullable=False),
    Column("path_key", String, nullable=False, unique=True),
    Column("active", Integer, nullable=False, server_default=text("1")),
    Column("last_scanned_at", String, nullable=True),
)

scan_jobs = Table(
    "scan_jobs",
    metadata,
    Column("id", String, primary_key=True),
    Column("state", String, nullable=False),
    Column("folders", Integer, nullable=False, server_default=text("0")),
    Column("found", Integer, nullable=False, server_default=text("0")),
    Column("skipped", Integer, nullable=False, server_default=text("0")),
    Column("complete", Integer, nullable=False, server_default=text("0")),
    Column("code", String, nullable=True),
    Column("started_at", String, nullable=False),
    Column("finished_at", String, nullable=True),
    CheckConstraint(
        "state IN ('running', 'done', 'failed', 'cancelled', 'interrupted')",
        name="ck_scan_jobs_state",
    ),
    Index("ix_scan_jobs_started", "started_at"),
)

scan_items = Table(
    "scan_items",
    metadata,
    Column("id", String, primary_key=True),
    Column("root_id", String, ForeignKey("scan_roots.id"), nullable=False),
    Column("path", String, nullable=False),
    Column("path_key", String, nullable=False, unique=True),
    Column("kind_folder", String, nullable=False),
    Column("maker", String, nullable=False),
    Column("maker_key", String, nullable=False),
    Column("title", String, nullable=False),
    Column("title_key", String, nullable=False),
    Column("state", String, nullable=False),
    Column("reason", String, nullable=True),
    Column("candidates", Text, nullable=True),
    Column("work_id", String, nullable=True),
    Column("batch_id", String, nullable=True),
    Column("job_id", String, nullable=True),
    CheckConstraint(
        "state IN ('certain', 'likely', 'review', 'unmatched', 'linked', 'ignored')",
        name="ck_scan_items_state",
    ),
    Index("ix_scan_items_state", "state", "maker_key", "title_key"),
)

save_configs = Table(
    "save_configs",
    metadata,
    Column("work_id", String, ForeignKey("works.id"), primary_key=True),
    Column("rules", Text, nullable=False),
    # Said out loud by the user. No rule on file is not the same as no saves.
    Column("confirmed_none", Integer, nullable=False, server_default=text("0")),
    Column("updated_at", String, nullable=False),
)

save_backups = Table(
    "save_backups",
    metadata,
    Column("id", String, primary_key=True),
    Column("work_id", String, ForeignKey("works.id"), nullable=False),
    Column("path", String, nullable=False),
    Column("rules", Text, nullable=False),
    Column("manifest", Text, nullable=False),
    Column("created_at", String, nullable=False),
    Index("ix_save_backups_work", "work_id", "created_at"),
)

game_updates = Table(
    "game_updates",
    metadata,
    Column("id", String, primary_key=True),
    Column("work_id", String, ForeignKey("works.id"), nullable=False),
    Column("copy_id", String, nullable=False),
    Column("state", String, nullable=False),
    Column("active_key", String, nullable=True, unique=True),  # One update per copy.
    Column("root_path", String, nullable=False),
    Column("staging_path", String, nullable=True),
    Column("old_path", String, nullable=True),
    Column("backup_id", String, nullable=True),
    Column("source_task_ids", Text, nullable=True),
    Column("error_code", String, nullable=True),
    Column("extra_count", Integer, nullable=True),
    Column("extra_sample", Text, nullable=True),
    Column("cleanup_failed", Integer, nullable=False, server_default=text("0")),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
    Column("finished_at", String, nullable=True),
    CheckConstraint(
        "state IN ('queued', 'backing_up', 'downloading', 'unpacking', 'replacing', "
        "'awaiting_confirmation', 'cleaning', 'done', 'failed', 'cancelled', 'interrupted', "
        "'rolled_back')",
        name="ck_game_updates_state",
    ),
    Index("ix_game_updates_work", "work_id", "created_at"),
)

media_progress = Table(
    "media_progress",
    metadata,
    Column("resource_id", String, primary_key=True),
    Column("work_id", String, ForeignKey("works.id"), nullable=False),
    Column("kind", String, nullable=False),
    Column("position", Float, nullable=False),
    Column("total", Float, nullable=True),
    Column("stamp", String, nullable=False),  # Which version of the file this is about.
    Column("updated_at", String, nullable=False),
    Index("ix_media_progress_work", "work_id", "kind"),
)

media_bookmarks = Table(
    "media_bookmarks",
    metadata,
    Column("id", String, primary_key=True),
    Column("work_id", String, ForeignKey("works.id"), nullable=False),
    Column("kind", String, nullable=False),
    Column("resource_id", String, nullable=False),
    Column("position", Float, nullable=False),
    Column("label", String, nullable=True),
    Column("stamp", String, nullable=False),
    Column("created_at", String, nullable=False),
    Index("ix_media_bookmarks_work", "work_id", "kind"),
)

playlists = Table(
    "playlists",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("created_at", String, nullable=False),
)

playlist_items = Table(
    "playlist_items",
    metadata,
    Column("playlist_id", String, ForeignKey("playlists.id"), primary_key=True),
    Column("position", Integer, primary_key=True),
    Column("copy_id", String, nullable=False),
    Column("track_id", String, nullable=False),
    Column("work_id", String, ForeignKey("works.id"), nullable=False),
    Column("name", String, nullable=False),
)

reading_progress = Table(
    "reading_progress",
    metadata,
    Column("book_id", String, primary_key=True),
    Column("work_id", String, ForeignKey("works.id"), nullable=False),
    Column("page_id", String, nullable=True),
    Column("page_index", Integer, nullable=False),
    Column("page_count", Integer, nullable=True),
    Column("read_state", String, nullable=False),  # unread | reading | read
    Column("updated_at", String, nullable=False),
    Index("ix_reading_progress_work", "work_id"),
)

reader_bookmarks = Table(
    "reader_bookmarks",
    metadata,
    Column("id", String, primary_key=True),
    Column("work_id", String, ForeignKey("works.id"), nullable=False),
    Column("book_id", String, nullable=False),
    Column("page_id", String, nullable=False),
    Column("page_index", Integer, nullable=False),
    Column("created_at", String, nullable=False),
    Index("ix_reader_bookmarks_book", "book_id"),
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
