"""Use cases behind the API: turn repository rows into contract objects."""

import json
from datetime import date
from typing import Any, cast

from sqlalchemy import Connection, Engine, Row, select

from app.api import models
from app.core.errors import NothingToUpdate
from app.db.schema import source_accounts
from app.domain.dashboard import aggregate
from app.repositories import works as repo


def _bool(value: int | None) -> bool | None:
    return None if value is None else bool(value)


def _cover(row: Row[Any]) -> models.Cover:
    # Real image assets arrive with sync (checkpoint 3). Synthetic samples draw locally.
    ref: str | None = row.cover_ref
    if ref and ref.startswith("synthetic:"):
        return models.Cover(kind="procedural", index=int(ref.removeprefix("synthetic:")))
    return models.Cover(kind="missing", index=0)


def _file_ref(files: list[Row[Any]]) -> models.FileRef | None:
    if not files:
        return None
    return models.FileRef(version=files[0].version, size_bytes=files[0].size_bytes)


def _work_fields(row: Row[Any], files: list[Row[Any]]) -> dict[str, Any]:
    return {
        "id": row.id,
        "platform": row.source_id,
        "source_id": row.source_work_id,
        "kind": row.kind,
        "maker": row.maker,
        "release_date": row.release_date,
        "title": row.title,
        "subtitle": row.subtitle,
        "genre": row.genre,
        "status": row.status,
        "installed": None if row.local_state == "unknown" else row.local_state == "available",
        "playtime_minutes": row.playtime_minutes,
        "favorite": bool(row.favorite),
        "cover": _cover(row),
        "added_at": row.added_at,
        "last_played_at": row.last_used_at,
        "capabilities": models.Capabilities(
            download=_bool(row.can_download),
            extract=_bool(row.can_extract),
            official_viewer_only=_bool(row.official_viewer_only),
        ),
        "file": _file_ref(files),
    }


def _work(row: Row[Any], files: list[Row[Any]]) -> models.WorkOut:
    return models.WorkOut(**_work_fields(row, files))


def _detail(connection: Connection, row: Row[Any]) -> models.WorkDetailOut:
    files = repo.files_for(connection, [row.id])[row.id]
    achievements = (
        models.Achievements(unlocked=row.achievements_unlocked, total=row.achievements_total)
        if row.achievements_total is not None
        else None
    )
    return models.WorkDetailOut(
        **_work_fields(row, files),
        description=row.description,
        tags=json.loads(row.tags_json),
        categories=[],
        achievements=achievements,
        rating=row.rating,
        note=row.note,
        version=row.version,
        files=[
            models.WorkFileOut(
                id=file.id,
                label=file.label,
                version=file.version,
                language=file.language,
                part_index=file.part_index,
                part_count=file.part_count,
                size_bytes=file.size_bytes,
                format=file.format,
                availability=file.availability,
                download_state=file.download_state,
                extract_state=file.extract_state,
            )
            for file in files
        ],
    )


def list_page(engine: Engine, query: models.WorkQuery) -> models.WorkPage:
    filters = repo.WorkFilters(
        search=query.search,
        kind=query.kind,
        platform=query.platform,
        genre=query.genre,
        status=query.status,
        installed=query.installed,
        favorites_only=query.favorites_only,
        sort=query.sort,
    )
    # One read transaction: rows and counts describe the same snapshot.
    with engine.connect() as connection:
        rows, filtered = repo.list_works(
            connection, filters, offset=query.offset, limit=query.limit
        )
        facets = repo.library_facets(connection, filters)
        files = repo.files_for(connection, [row.id for row in rows])
    return models.WorkPage(
        items=[_work(row, files[row.id]) for row in rows],
        offset=query.offset,
        limit=query.limit,
        filtered_count=filtered,
        **facets,
    )


def get_detail(engine: Engine, work_id: str) -> models.WorkDetailOut:
    with engine.connect() as connection:
        return _detail(connection, repo.get_ordinary_work(connection, work_id))


def update_personal(
    engine: Engine, work_id: str, body: models.PersonalUpdate
) -> models.WorkDetailOut:
    fields = body.model_dump(exclude_unset=True, exclude={"expected_version"})
    # Only a rating can be cleared with null; the other fields have no empty value.
    values = {
        name: value for name, value in fields.items() if value is not None or name == "rating"
    }
    if "favorite" in values:
        values["favorite"] = int(values["favorite"])
    if not values:
        raise NothingToUpdate
    # A single transaction: the response is exactly what this write produced.
    with engine.begin() as connection:
        repo.update_personal(
            connection,
            work_id,
            repo.PersonalChanges(values=values, expected_version=body.expected_version),
        )
        return _detail(connection, repo.get_ordinary_work(connection, work_id))


def toggle_favorite(engine: Engine, work_id: str) -> models.WorkDetailOut:
    with engine.begin() as connection:
        repo.toggle_favorite(connection, work_id)
        return _detail(connection, repo.get_ordinary_work(connection, work_id))


def dashboard(engine: Engine, query: models.DashboardQuery) -> models.DashboardOut:
    # The day and batch seed the picks: stable within a day, changing with 换一批.
    seed = f"{date.today().isoformat()}:{query.batch}"
    with engine.connect() as connection:
        summary, picks = aggregate(repo.dashboard_facts(connection), query.scope, seed)
        recommended = [work_id for work_id, _ in picks.recommendations]
        wanted = [*picks.featured, *picks.recent, *picks.most_played, *recommended]
        rows = repo.get_ordinary_works(connection, wanted)
        files = repo.files_for(connection, rows)

    def out(work_id: str) -> models.WorkOut:
        return _work(rows[work_id], files[work_id])

    return models.DashboardOut(
        featured=[out(work_id) for work_id in picks.featured],
        recent=[out(work_id) for work_id in picks.recent],
        most_played=[out(work_id) for work_id in picks.most_played],
        recommendations=[
            models.Recommendation(game=out(work_id), reasons=reasons)
            for work_id, reasons in picks.recommendations
        ],
        **cast(dict[str, Any], summary),
    )


def source_status(engine: Engine) -> models.SourcesOut:
    with engine.connect() as connection:
        rows = repo.source_summaries(connection)
        accounts = {
            row.source_id: row.state
            for row in connection.execute(
                select(source_accounts.c.source_id, source_accounts.c.state)
            )
        }
    return models.SourcesOut(
        sources=[
            models.SourceOut(
                id=row.id,
                display_name=row.display_name,
                # A source row alone never implies an authenticated account.
                connection=accounts.get(row.id, "not_connected"),
                work_count=row.work_count,
            )
            for row in rows
        ]
    )
