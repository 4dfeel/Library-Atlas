"""Request and response contract. JSON field names are camelCase; see docs/LOCAL_API.md."""

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StrictBool,
    StrictInt,
    StringConstraints,
)
from pydantic.alias_generators import to_camel

Platform = Literal["steam", "dlsite"]
WorkKind = Literal["game", "image", "video", "audio", "other"]
Status = Literal["unplayed", "playing", "completed", "paused"]
Sort = Literal[
    "curated",
    "name-asc",
    "name-desc",
    "playtime-desc",
    "playtime-asc",
    "added-desc",
    "added-asc",
    "maker-asc",
    "maker-desc",
    "genre-asc",
    "genre-desc",
    "rating-desc",
    "rating-asc",
    "release-desc",
    "release-asc",
    "size-desc",
    "size-asc",
]
NOTE_MAX_LENGTH = 1000


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class WorkQuery(ApiModel):
    # Unknown parameters are rejected, so no flag can widen the ordinary scope.
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    search: Annotated[str, StringConstraints(max_length=200)] = ""
    kind: Literal["all", "non-game", "game", "image", "video", "audio", "other"] = "all"
    platform: Literal["all", "steam", "dlsite"] = "all"
    genre: Annotated[str, StringConstraints(max_length=200)] = "all"
    status: Literal["all", "unplayed", "playing", "completed", "paused"] = "all"
    installed: Literal["all", "installed", "not-installed"] = "all"
    favorites_only: bool = False
    sort: Sort = "curated"
    offset: Annotated[int, Field(ge=0, le=1_000_000)] = 0
    limit: Annotated[int, Field(ge=1, le=100)] = 100


class DashboardQuery(ApiModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    scope: Literal["all", "games", "steam", "dlsite-games", "dlsite-media"] = "all"
    batch: Annotated[int, Field(ge=0, le=1_000_000)] = 0


class PersonalUpdate(ApiModel):
    """Only these personal fields are writable; visibility and observations are not."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    status: Status | None = None
    rating: Annotated[StrictInt, Field(ge=1, le=5)] | None = None
    note: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=NOTE_MAX_LENGTH)] | None
    ) = None
    favorite: StrictBool | None = None
    expected_version: Annotated[StrictInt, Field(ge=1)] | None = None


class Cover(ApiModel):
    kind: Literal["procedural", "remote", "missing"]
    index: int
    # Atlas's own address for a cached platform image, never the platform's.
    url: str | None = None


class Capabilities(ApiModel):
    """`null` means not known yet, which is not the same as unsupported."""

    download: bool | None
    extract: bool | None
    official_viewer_only: bool | None


class FileRef(ApiModel):
    version: str | None
    size_bytes: int | None


class WorkFileOut(ApiModel):
    id: str
    label: str | None
    version: str | None
    language: str | None
    part_index: int | None
    part_count: int | None
    size_bytes: int | None
    format: str | None
    availability: Literal["unknown", "downloadable", "viewer_only"]
    download_state: Literal["unknown", "not_downloaded", "downloaded"]
    extract_state: Literal["unknown", "not_applicable", "not_extracted", "extracted"]


class WorkOut(ApiModel):
    id: str
    platform: Platform
    source_id: str
    kind: WorkKind
    maker: str | None
    release_date: str | None
    title: str
    subtitle: str | None
    genre: str | None
    status: Status
    installed: bool | None
    playtime_minutes: int | None
    favorite: bool
    visibility: Literal["normal"] = "normal"
    cover: Cover
    background: None = None
    added_at: str
    last_played_at: str | None
    capabilities: Capabilities
    file: FileRef | None
    source_url: str | None = None
    rating: int | None = None


class Achievements(ApiModel):
    unlocked: int
    total: int


class WorkDetailOut(WorkOut):
    description: str | None
    tags: list[str]
    categories: list[str]
    achievements: Achievements | None
    note: str
    version: int
    files: list[WorkFileOut]


class WorkPage(ApiModel):
    items: list[WorkOut]
    offset: int
    limit: int
    filtered_count: int
    total_visible: int
    genres: list[str]
    installed_count: int
    favorite_count: int
    kind_counts: dict[WorkKind, int]


class Recommendation(ApiModel):
    game: WorkOut
    reasons: list[str]


class DashboardTotals(ApiModel):
    works: int
    games: int
    played_games: int
    unstarted_games: int
    unknown_playtime_games: int
    playtime_minutes: int
    non_games: int
    used_non_games: int
    local: int
    favorites: int


class DashboardOut(ApiModel):
    scope: str
    has_games: bool
    totals: DashboardTotals
    featured: list[WorkOut]
    recent: list[WorkOut]
    most_played: list[WorkOut]
    recommendations: list[Recommendation]
    playtime_buckets: list[dict[str, Any]]
    genres: list[dict[str, Any]]
    kinds: list[dict[str, Any]]
    backlog: dict[Status, int]
    sources: dict[Platform, dict[str, int]]


class SourceCapabilities(ApiModel):
    """What Atlas can do with this source today."""

    connect: bool = False
    sync: bool = False
    download: bool = False


ConnectionState = Literal[
    "not_connected",
    "authenticating",
    "needs_verification",
    "verifying",
    "connected",
    "unverified",
    "reauth_required",
    "disconnect_failed",
    "error",
]


class DlsiteConnection(ApiModel):
    """Safe to show. Never holds the account name, session or any platform response."""

    state: ConnectionState
    code: str | None = None
    message: str | None = None
    last_verified_at: str | None = None
    can_reveal: bool = False
    # Masked account name; absent after web login, where Atlas never sees the name.
    account_alias: str | None = None
    # Masked name of a remembered login. The password itself never leaves the service.
    remembered_account: str | None = None


class DlsiteLogin(ApiModel):
    """`SecretStr`: a stray log or repr shows asterisks, not the password."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    login_id: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    password: Annotated[SecretStr, Field(min_length=1, max_length=256)]
    confirm_switch: StrictBool = False
    remember: StrictBool = False


SyncState = Literal[
    "preparing",
    "reading",
    "saving",
    "succeeded",
    "partial",
    "failed",
    "cancelled",
    "reauth_required",
    "interrupted",
]


class SyncJob(ApiModel):
    id: str
    state: SyncState
    total: int | None
    processed: int
    added: int
    updated: int
    skipped: int
    missing: int
    code: str | None = None
    message: str | None = None
    started_at: str
    finished_at: str | None = None


class SyncStatus(ApiModel):
    """`lastSyncedAt` changes only after a complete sync, not after every attempt."""

    last_synced_at: str | None = None
    job: SyncJob | None = None


FolderKind = Literal["library", "download_cache"]
FolderStatus = Literal["ok", "not_set", "missing"]


class FolderOut(ApiModel):
    kind: FolderKind
    path: str | None
    is_default: bool
    status: FolderStatus


class FoldersOut(ApiModel):
    folders: list[FolderOut]


DownloadState = Literal[
    "queued",
    "resolving",
    "downloading",
    "verifying",
    "paused",
    "done",
    "failed",
    "cancelled",
    "reauth_required",
    "interrupted",
]


class DownloadTaskOut(ApiModel):
    """Never holds a download address. `location` is set only once a task is done."""

    id: str
    work_id: str
    title: str
    part: int | None
    part_count: int | None
    state: DownloadState
    bytes_done: int
    bytes_total: int | None  # None when the server does not say: never shown as 0.
    file_name: str | None
    code: str | None
    message: str | None
    can_retry: bool
    can_resume: bool
    integrity: str | None
    location: str | None
    file_missing: bool
    archive_removed: bool = False
    dismissed: bool = False
    # Measured over the last moments of a running transfer; None until there is a sample.
    bytes_per_second: int | None = None
    created_at: str
    finished_at: str | None


class DownloadUpdate(ApiModel):
    """A downloaded work the platform has changed since. Not downloaded until the user asks."""

    work_id: str
    title: str
    size_bytes: int | None = None


class DownloadsOut(ApiModel):
    tasks: list[DownloadTaskOut]
    active_count: int
    updates: list[DownloadUpdate] = []


class UpdateSettings(ApiModel):
    auto_check: bool
    last_checked_at: str | None


class UpdateSettingsIn(ApiModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    auto_check: bool


CopyOrigin = Literal["manual", "unpacked", "scanned"]
CopyStatus = Literal["ok", "no_entry", "root_missing", "offline", "entry_missing"]


class LocalCopyOut(ApiModel):
    id: str
    work_id: str
    root: str
    entry: str | None
    working: str | None
    arguments: list[str]
    label: str | None
    is_default: bool
    origin: CopyOrigin
    status: CopyStatus
    message: str


class LocalCopiesOut(ApiModel):
    copies: list[LocalCopyOut]


class LocalCopyIn(ApiModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    root: Annotated[str, StringConstraints(min_length=1, max_length=1024)]
    entry: Annotated[str, StringConstraints(max_length=1024)] | None = None
    working: Annotated[str, StringConstraints(max_length=1024)] | None = None
    arguments: list[str] = []
    label: Annotated[str, StringConstraints(max_length=120)] | None = None
    make_default: bool = False


class LocalCopyUpdate(ApiModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    root: Annotated[str, StringConstraints(max_length=1024)] | None = None
    entry: Annotated[str, StringConstraints(max_length=1024)] | None = None
    working: Annotated[str, StringConstraints(max_length=1024)] | None = None
    arguments: list[str] | None = None
    label: Annotated[str, StringConstraints(max_length=120)] | None = None


class CopyPreviewIn(ApiModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    path: Annotated[str, StringConstraints(min_length=1, max_length=1024)]


class CopyEntryOut(ApiModel):
    path: str
    likely_helper: bool


class CopyPreviewOut(ApiModel):
    root: str
    entries: list[CopyEntryOut]
    suggested: str | None


class ChosenFolderOut(ApiModel):
    path: str | None


class LaunchOut(ApiModel):
    """`submitted` means Windows was asked to start it. Nothing more is known."""

    submitted: bool
    repeated: bool = False


IntroStatus = Literal["ok", "empty", "unavailable"]


class IntroOut(ApiModel):
    """Checked blocks in page order. "empty" means the platform has none; "unavailable" means
    Atlas could not tell, and never replaces what was read before."""

    status: IntroStatus
    blocks: list[dict[str, Any]]
    fetched_at: str | None = None
    stale: bool = False
    problem: str | None = None
    message: str | None = None


class GalleryImage(ApiModel):
    """An Atlas address. The platform's own address never reaches the page."""

    url: str
    width: int | None = None
    height: int | None = None


class GalleryOut(ApiModel):
    images: list[GalleryImage]
    intro: str | None = None
    unavailable: bool = False


class DownloadPlanOut(ApiModel):
    kind: Literal["direct", "split", "serial"]
    parts: list[int]
    total_bytes: int | None
    folder: FolderOut
    free_bytes: int | None


class DownloadCreate(ApiModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    work_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    parts: Annotated[list[int], Field(max_length=500)] | None = None
    again: bool = False
    extract: bool = False  # Only ever from the user's own choice of "download and unpack".


ExtractState = Literal[
    "queued",
    "checking",
    "extracting",
    "committing",
    "done",
    "not_needed",
    "failed",
    "cancelled",
    "interrupted",
]


class ExtractTaskOut(ApiModel):
    id: str
    work_id: str
    title: str
    state: ExtractState
    format: str | None
    files_total: int | None
    bytes_total: int | None
    bytes_done: int
    code: str | None
    message: str | None
    can_retry: bool
    location: str | None
    result_missing: bool
    cleanup_failed: bool
    dismissed: bool = False
    created_at: str
    finished_at: str | None


class ExtractionsOut(ApiModel):
    tasks: list[ExtractTaskOut]
    active_count: int


class ExtractCreate(ApiModel):
    """Names a work, never a file: what gets unpacked is decided from its finished downloads."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    work_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    again: bool = False


class FolderUpdate(ApiModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    path: Annotated[str, StringConstraints(min_length=1, max_length=1024)]


class SourceOut(ApiModel):
    id: Platform
    display_name: str
    connection: ConnectionState
    work_count: int
    last_sync_at: str | None = None
    capabilities: SourceCapabilities = SourceCapabilities()


class SourcesOut(ApiModel):
    sources: list[SourceOut]


class HealthOut(ApiModel):
    status: Literal["ok"] = "ok"
    version: str


class ReadyOut(ApiModel):
    status: Literal["ready", "not_ready"]
    profile: Literal["real", "test"]
    schema_revision: str | None = None
    reason: str | None = None
    message: str | None = None


class SessionOut(ApiModel):
    csrf_token: str
