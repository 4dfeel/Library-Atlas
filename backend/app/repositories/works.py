"""SQL for works and personal records. Parameterized through SQLAlchemy Core.

Every ordinary read and write goes through `ORDINARY`: visibility is applied before
search, facets, counts, aggregates and by-ID access, in this one place.
"""

import json
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import (
    ColumnElement,
    Connection,
    Row,
    and_,
    case,
    exists,
    func,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.sqlite import insert

from app.core.errors import VersionConflict, WorkUnavailable
from app.db.schema import (
    collection_items,
    library_entries,
    local_copies,
    personal_records,
    sources,
    work_files,
    works,
)
from app.domain.dashboard import WorkFacts
from app.domain.text import normalize, search_text, sort_title

ORDINARY: ColumnElement[bool] = personal_records.c.visibility == "normal"

_JOINED = works.join(personal_records, personal_records.c.work_id == works.c.id).join(
    library_entries, library_entries.c.work_id == works.c.id
)
# The folder a work is used from: the default copy, or else the oldest.
_FIRST_COPY = (
    select(local_copies)
    .where(local_copies.c.work_id == works.c.id)
    .order_by(local_copies.c.is_default.desc(), local_copies.c.created_at)
    .limit(1)
)
_WORK_COLUMNS = (
    works,
    _FIRST_COPY.with_only_columns(local_copies.c.id).scalar_subquery().label("copy_id"),
    _FIRST_COPY.with_only_columns(local_copies.c.entry_path).scalar_subquery().label("copy_entry"),
    personal_records.c.status,
    personal_records.c.rating,
    personal_records.c.note,
    personal_records.c.favorite,
    personal_records.c.version,
    library_entries.c.added_at,
)

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


@dataclass(frozen=True)
class WorkFilters:
    search: str = ""
    kind: str = "all"
    platform: str = "all"
    genre: str = "all"
    status: str = "all"
    installed: str = "all"
    favorites_only: bool = False
    collection: str = "all"
    sort: Sort = "curated"


@dataclass(frozen=True)
class SourceMetadata:
    """Everything a sync may write. Personal fields are intentionally not here."""

    source_id: str
    source_work_id: str
    title: str
    kind: str = "other"
    raw_kind: str | None = None
    subtitle: str | None = None
    maker: str | None = None
    genre: str | None = None
    description: str | None = None
    release_date: str | None = None
    cover_ref: str | None = None
    backdrop_ref: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    playtime_minutes: int | None = None
    last_used_at: str | None = None
    achievements_unlocked: int | None = None
    achievements_total: int | None = None
    local_state: str = "unknown"
    can_download: bool | None = None
    can_extract: bool | None = None
    official_viewer_only: bool | None = None
    # Other spellings of the title: searchable, not displayed.
    alt_titles: tuple[str, ...] = field(default_factory=tuple)
    source_url: str | None = None
    download_size: int | None = None
    upgraded_at: str | None = None


@dataclass(frozen=True)
class WorkFile:
    label: str | None = None
    version: str | None = None
    language: str | None = None
    part_index: int | None = None
    part_count: int | None = None
    size_bytes: int | None = None
    format: str | None = None
    availability: str = "unknown"
    download_state: str = "unknown"
    extract_state: str = "unknown"


@dataclass(frozen=True)
class PersonalChanges:
    values: dict[str, Any]
    expected_version: int | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat()


_HAS_COPY = exists().where(local_copies.c.work_id == works.c.id)
_ON_THIS_MACHINE = or_(works.c.local_state == "available", _HAS_COPY)


def _kind_clause(kind: str) -> ColumnElement[bool] | None:
    if kind == "all":
        return None
    if kind == "non-game":
        return works.c.kind != "game"
    return works.c.kind == kind


def _local_clause(installed: str) -> ColumnElement[bool] | None:
    # "Not on this machine" needs a known absence: unknown never counts as absent.
    if installed == "installed":
        return _ON_THIS_MACHINE
    if installed == "not-installed":
        return and_(works.c.local_state == "absent", ~_HAS_COPY)
    return None


def _filter_clauses(filters: WorkFilters) -> list[ColumnElement[bool]]:
    clauses: list[ColumnElement[bool]] = [ORDINARY]
    term = normalize(filters.search.strip())
    if term:
        clauses.append(works.c.search_text.contains(term, autoescape=True))
    kind = _kind_clause(filters.kind)
    if kind is not None:
        clauses.append(kind)
    if filters.platform != "all":
        clauses.append(works.c.source_id == filters.platform)
    if filters.genre != "all":
        clauses.append(works.c.genre == filters.genre)
    if filters.status != "all":
        clauses.append(personal_records.c.status == filters.status)
    local = _local_clause(filters.installed)
    if local is not None:
        clauses.append(local)
    if filters.favorites_only:
        clauses.append(personal_records.c.favorite == 1)
    if filters.collection != "all":
        clauses.append(
            works.c.id.in_(
                select(collection_items.c.work_id).where(
                    collection_items.c.collection_id == filters.collection
                )
            )
        )
    return clauses


def _ordering(sort: Sort) -> tuple[Any, ...]:
    """Always ends in the ID, so pages never skip or repeat a row. Anything not reported
    goes last in either direction: unknown is not smallest and not largest."""
    columns: dict[str, Any] = {
        "added": library_entries.c.added_at,
        "maker": works.c.maker,
        "genre": works.c.genre,
        "rating": personal_records.c.rating,
        "release": works.c.release_date,
        "size": works.c.download_size,
    }
    field, _, direction = sort.partition("-")
    if field in columns:
        column = columns[field]
        ordered = column.desc() if direction == "desc" else column.asc()
        return (column.is_(None).asc(), ordered, works.c.id.asc())
    match sort:
        case "name-asc":
            return (works.c.sort_title.asc(), works.c.id.asc())
        case "name-desc":
            return (works.c.sort_title.desc(), works.c.id.asc())
        case "playtime-desc":
            return (
                works.c.playtime_minutes.is_(None).asc(),
                works.c.playtime_minutes.desc(),
                works.c.id.asc(),
            )
        case "playtime-asc":
            # Unknown play time stays last in either direction.
            return (
                works.c.playtime_minutes.is_(None).asc(),
                works.c.playtime_minutes.asc(),
                works.c.id.asc(),
            )
        case _:
            return (library_entries.c.added_at.desc(), works.c.id.asc())


def list_works(
    connection: Connection, filters: WorkFilters, *, offset: int, limit: int
) -> tuple[Sequence[Row[Any]], int]:
    clauses = _filter_clauses(filters)
    total = connection.execute(
        select(func.count()).select_from(_JOINED).where(*clauses)
    ).scalar_one()
    rows = connection.execute(
        select(*_WORK_COLUMNS)
        .select_from(_JOINED)
        .where(*clauses)
        .order_by(*_ordering(filters.sort))
        .offset(offset)
        .limit(limit)
    ).all()
    return rows, total


def library_facets(connection: Connection, filters: WorkFilters) -> dict[str, Any]:
    """Counts over all ordinary works, independent of the other active filters."""
    base = select(func.count()).select_from(_JOINED).where(ORDINARY)
    kind_rows = connection.execute(
        select(works.c.kind, func.count())
        .select_from(_JOINED)
        .where(ORDINARY)
        .group_by(works.c.kind)
    ).all()
    kind_counts = {kind: 0 for kind in ("game", "image", "video", "audio", "other")}
    kind_counts.update({row[0]: row[1] for row in kind_rows})
    genre_query = (
        select(works.c.genre)
        .select_from(_JOINED)
        .where(ORDINARY, works.c.genre.is_not(None))
        .distinct()
        .order_by(works.c.genre)
    )
    kind = _kind_clause(filters.kind)
    if kind is not None:
        genre_query = genre_query.where(kind)
    return {
        "total_visible": sum(kind_counts.values()),
        "kind_counts": kind_counts,
        "genres": list(connection.execute(genre_query).scalars()),
        "installed_count": connection.execute(base.where(_ON_THIS_MACHINE)).scalar_one(),
        "favorite_count": connection.execute(
            base.where(personal_records.c.favorite == 1)
        ).scalar_one(),
    }


def get_ordinary_work(connection: Connection, work_id: str) -> Row[Any]:
    row = connection.execute(
        select(*_WORK_COLUMNS).select_from(_JOINED).where(ORDINARY, works.c.id == work_id)
    ).first()
    if row is None:
        raise WorkUnavailable
    return row


def get_ordinary_works(connection: Connection, ids: Iterable[str]) -> dict[str, Row[Any]]:
    wanted = list(dict.fromkeys(ids))
    if not wanted:
        return {}
    rows = connection.execute(
        select(*_WORK_COLUMNS).select_from(_JOINED).where(ORDINARY, works.c.id.in_(wanted))
    ).all()
    return {row.id: row for row in rows}


def files_for(connection: Connection, ids: Iterable[str]) -> dict[str, list[Row[Any]]]:
    wanted = list(ids)
    grouped: dict[str, list[Row[Any]]] = defaultdict(list)
    if not wanted:
        return grouped
    rows = connection.execute(
        select(work_files)
        .where(work_files.c.work_id.in_(wanted))
        .order_by(work_files.c.work_id, work_files.c.position, work_files.c.id)
    ).all()
    for row in rows:
        grouped[row.work_id].append(row)
    return grouped


def dashboard_facts(connection: Connection) -> list[WorkFacts]:
    rows = connection.execute(
        select(
            works.c.id,
            works.c.source_id,
            works.c.kind,
            works.c.genre,
            personal_records.c.status,
            works.c.local_state,
            _HAS_COPY.label("has_copy"),
            personal_records.c.favorite,
            works.c.cover_ref,
            works.c.playtime_minutes,
            works.c.last_used_at,
        )
        .select_from(_JOINED)
        .where(ORDINARY)
    ).all()
    return [
        WorkFacts(
            id=row.id,
            platform=row.source_id,
            kind=row.kind,
            genre=row.genre,
            status=row.status,
            local=(
                True
                if row.has_copy
                else None
                if row.local_state == "unknown"
                else row.local_state == "available"
            ),
            favorite=bool(row.favorite),
            has_cover=row.cover_ref is not None,
            playtime_minutes=row.playtime_minutes,
            last_used_at=row.last_used_at,
        )
        for row in rows
    ]


def source_summaries(connection: Connection) -> Sequence[Row[Any]]:
    """One row per source with its ordinary-work count."""
    counts = (
        select(works.c.source_id, func.count().label("work_count"))
        .select_from(_JOINED)
        .where(ORDINARY)
        .group_by(works.c.source_id)
        .subquery()
    )
    return connection.execute(
        select(
            sources.c.id,
            sources.c.display_name,
            func.coalesce(counts.c.work_count, 0).label("work_count"),
        )
        .select_from(sources.outerjoin(counts, counts.c.source_id == sources.c.id))
        .order_by(case((sources.c.id == "steam", 0), else_=1))
    ).all()


def _bump(changes: dict[str, Any]) -> dict[str, Any]:
    return {**changes, "version": personal_records.c.version + 1, "updated_at": _now()}


def update_personal(connection: Connection, work_id: str, changes: PersonalChanges) -> None:
    """Writes only the given fields, so concurrent edits to other fields survive."""
    conditions = [personal_records.c.work_id == work_id, ORDINARY]
    if changes.expected_version is not None:
        conditions.append(personal_records.c.version == changes.expected_version)
    result = connection.execute(
        update(personal_records).where(*conditions).values(_bump(changes.values))
    )
    if result.rowcount == 0:
        get_ordinary_work(connection, work_id)  # Raises for private and absent IDs alike.
        raise VersionConflict


def toggle_favorite(connection: Connection, work_id: str) -> None:
    result = connection.execute(
        update(personal_records)
        .where(personal_records.c.work_id == work_id, ORDINARY)
        .values(_bump({"favorite": literal(1) - personal_records.c.favorite}))
    )
    if result.rowcount == 0:
        raise WorkUnavailable


def upsert_source_metadata(
    connection: Connection,
    metadata: SourceMetadata,
    *,
    work_id: str | None = None,
    visibility: str | None = None,
    keep_missing: bool = False,
    acquired_at: str | None = None,
) -> str:
    """Idempotent on (source, source work ID). Never writes personal records of a known
    work: `visibility` and `acquired_at` only apply to a work seen for the first time, which
    otherwise starts quarantined. With `keep_missing`, a field this response did not provide
    keeps its stored value instead of being cleared."""
    now = _now()
    values: dict[str, Any] = {
        "source_id": metadata.source_id,
        "source_work_id": metadata.source_work_id,
        "kind": metadata.kind,
        "raw_kind": metadata.raw_kind,
        "title": metadata.title,
        "subtitle": metadata.subtitle,
        "maker": metadata.maker,
        "genre": metadata.genre,
        "description": metadata.description,
        "release_date": metadata.release_date,
        "cover_ref": metadata.cover_ref,
        "backdrop_ref": metadata.backdrop_ref,
        "tags_json": json.dumps(list(metadata.tags), ensure_ascii=False),
        "playtime_minutes": metadata.playtime_minutes,
        "last_used_at": metadata.last_used_at,
        "achievements_unlocked": metadata.achievements_unlocked,
        "achievements_total": metadata.achievements_total,
        "local_state": metadata.local_state,
        "can_download": metadata.can_download,
        "can_extract": metadata.can_extract,
        "official_viewer_only": metadata.official_viewer_only,
        "search_text": search_text(
            metadata.title, metadata.subtitle, metadata.maker, *metadata.alt_titles
        ),
        "sort_title": sort_title(metadata.title),
        "metadata_updated_at": now,
        "source_url": metadata.source_url,
        "download_size": metadata.download_size,
        "upgraded_at": metadata.upgraded_at,
    }
    changes = values
    if keep_missing:
        changes = {name: value for name, value in values.items() if value is not None}
        if not metadata.tags:
            changes.pop("tags_json", None)
        # Facts this source does not report at all.
        for name in ("local_state", "subtitle"):
            changes.pop(name, None)
    statement = insert(works).values(id=work_id or f"wk_{uuid.uuid4().hex}", **values)
    identifier = connection.execute(
        statement.on_conflict_do_update(
            index_elements=[works.c.source_id, works.c.source_work_id], set_=changes
        ).returning(works.c.id)
    ).scalar_one()
    connection.execute(
        insert(library_entries)
        .values(work_id=identifier, ownership_status="observed_owned", added_at=acquired_at or now)
        .on_conflict_do_update(
            index_elements=[library_entries.c.work_id],
            set_={"ownership_status": "observed_owned"},
        )
    )
    personal: dict[str, Any] = {"work_id": identifier, "updated_at": now}
    if visibility is not None:
        personal["visibility"] = visibility
    connection.execute(insert(personal_records).values(**personal).on_conflict_do_nothing())
    return str(identifier)


def replace_work_files(connection: Connection, work_id: str, files: Sequence[WorkFile]) -> None:
    connection.execute(work_files.delete().where(work_files.c.work_id == work_id))
    if files:
        connection.execute(
            work_files.insert(),
            [
                {
                    "id": f"{work_id}:{position}",
                    "work_id": work_id,
                    "position": position,
                    "label": file.label,
                    "version": file.version,
                    "language": file.language,
                    "part_index": file.part_index,
                    "part_count": file.part_count,
                    "size_bytes": file.size_bytes,
                    "format": file.format,
                    "availability": file.availability,
                    "download_state": file.download_state,
                    "extract_state": file.extract_state,
                }
                for position, file in enumerate(files)
            ],
        )


def set_visibility(connection: Connection, work_id: str, visibility: str) -> None:
    """Repository-level only; no API exposes it before the private-space phase."""
    connection.execute(
        update(personal_records)
        .where(personal_records.c.work_id == work_id)
        .values(visibility=visibility, updated_at=_now())
    )
