"""The media files inside a work's linked folder, and what the user has done with them.

A page names a file by an ID that only means something inside a saved copy: no request can reach a
path. Files are found by walking the linked folder, without following links out of it, and the
list is kept briefly so paging through a large work does not walk it every time. Progress belongs
to one version of a file: if the file changes, the old position is not applied to the new one.
"""

import hashlib
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, Row, delete, select, update
from sqlalchemy.dialects.sqlite import insert

from app.api import models
from app.core.errors import AtlasError
from app.db.engine import writing
from app.db.schema import (
    local_copies,
    media_bookmarks,
    media_progress,
    playlist_items,
    playlists,
)
from app.repositories.works import get_ordinary_work

_CACHE_SECONDS = 30.0
_MAX_DEPTH = 10
_MAX_VISITED = 200_000
MAX_FILES = 20_000
# What current browsers play. A browser that refuses one anyway reports it when it is tried.
AUDIO_TYPES = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
}
# Found and listed, so a work is not shown as empty, but a browser cannot play them.
AUDIO_UNPLAYABLE = {".wma", ".ape", ".tak", ".tta", ".wv", ".mid", ".midi"}
IMAGE_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".avif": "image/avif",
}
_NUMBER = re.compile(r"(\d+)")


def natural_key(text: str) -> list[Any]:
    """`2` before `10`, as a person would count, whatever the case."""
    return [
        (0, int(part), "") if part.isdigit() else (1, 0, part.casefold())
        for part in _NUMBER.split(text)
    ]


def path_key(relative: str) -> list[Any]:
    return [natural_key(part) for part in relative.split("/")]


@dataclass(frozen=True)
class MediaFile:
    id: str
    relative: str  # Separated by "/".
    path: Path
    size: int
    stamp: str  # Changes when the file does.
    suffix: str


def _file_id(copy_id: str, relative: str) -> str:
    return hashlib.sha256(f"{copy_id}\0{relative.casefold()}".encode()).hexdigest()[:32]


def walk_media(copy_id: str, root: Path, suffixes: set[str]) -> tuple[list[MediaFile], bool]:
    """The matching files, in natural order, and whether the list was cut short."""
    found: list[MediaFile] = []
    visited = 0
    complete = True
    stack: list[tuple[str, str, int]] = [(str(root), "", 0)]
    while stack:
        folder, prefix, depth = stack.pop()
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    visited += 1
                    if visited > _MAX_VISITED or len(found) >= MAX_FILES:
                        complete = False
                        break
                    if entry.is_symlink() or entry.is_junction():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if depth < _MAX_DEPTH:
                            stack.append((entry.path, f"{prefix}{entry.name}/", depth + 1))
                        continue
                    suffix = os.path.splitext(entry.name)[1].lower()
                    if suffix in suffixes:
                        relative = f"{prefix}{entry.name}"
                        info = entry.stat(follow_symlinks=False)
                        found.append(
                            MediaFile(
                                _file_id(copy_id, relative),
                                relative,
                                Path(entry.path),
                                info.st_size,
                                f"{info.st_size}:{int(info.st_mtime)}",
                                suffix,
                            )
                        )
        except OSError:
            continue
    found.sort(key=lambda item: path_key(item.relative))
    return found, complete


def _now() -> str:
    return datetime.now(UTC).isoformat()


class LocalMedia:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._lock = threading.Lock()
        self._cache: dict[tuple[str, frozenset[str]], tuple[float, list[MediaFile], bool]] = {}

    # --- finding files ---

    def _copy_for(self, work_id: str, copy_id: str | None) -> Row[Any] | None:
        with self._engine.connect() as connection:
            get_ordinary_work(connection, work_id)
            statement = select(local_copies).where(local_copies.c.work_id == work_id)
            if copy_id:
                statement = statement.where(local_copies.c.id == copy_id)
            else:
                statement = statement.order_by(
                    local_copies.c.is_default.desc(), local_copies.c.created_at
                )
            return connection.execute(statement.limit(1)).first()

    def _ordinary_copy(self, copy_id: str) -> Row[Any]:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(local_copies).where(local_copies.c.id == copy_id)
            ).first()
            if row is None:
                raise AtlasError("media_not_found", "找不到这个文件。", status=404)
            get_ordinary_work(connection, row.work_id)
        return row

    def files(self, copy_id: str, root: Path, suffixes: set[str]) -> tuple[list[MediaFile], bool]:
        key = (copy_id, frozenset(suffixes))
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and now - cached[0] < _CACHE_SECONDS:
                return cached[1], cached[2]
        files, complete = walk_media(copy_id, root, suffixes)
        with self._lock:
            self._cache[key] = (now, files, complete)
        return files, complete

    def forget(self, copy_id: str) -> None:
        with self._lock:
            for key in [key for key in self._cache if key[0] == copy_id]:
                del self._cache[key]

    def resolve(self, copy_id: str, file_id: str, types: dict[str, str]) -> tuple[Path, str]:
        """A saved copy and an ID found by looking, never a path from the request. The file is
        checked again here: it may have been replaced by a link since it was listed."""
        row = self._ordinary_copy(copy_id)
        root = Path(row.root_path)
        if not root.is_dir():
            raise AtlasError("media_offline", "这个文件夹现在不可用。", status=404)
        files, _complete = self.files(copy_id, root, set(types))
        match = next((item for item in files if item.id == file_id), None)
        if match is None:
            self.forget(copy_id)
            raise AtlasError("media_not_found", "找不到这个文件。", status=404)
        if not match.path.is_file() or not match.path.resolve().is_relative_to(root.resolve()):
            self.forget(copy_id)
            raise AtlasError("media_not_found", "这个文件已经不在了。", status=404)
        return match.path, types[match.suffix]

    # --- audio ---

    def audio(self, work_id: str) -> models.AudioOut:
        row = self._copy_for(work_id, None)
        if row is None:
            return models.AudioOut(state="no_copy", tracks=[])
        root = Path(row.root_path)
        if not root.is_dir():
            return models.AudioOut(state="offline", copy_id=row.id, tracks=[])
        files, complete = self.files(row.id, root, {*AUDIO_TYPES, *AUDIO_UNPLAYABLE})
        progress = self._progress(work_id, "audio")
        latest: tuple[str, str] | None = None
        tracks = []
        for item in files:
            saved = progress.get(item.id)
            # A changed file is a different recording: its old place means nothing.
            if saved is not None and saved.stamp != item.stamp:
                saved = None
            if saved is not None and (latest is None or saved.updated_at > latest[1]):
                latest = (item.id, saved.updated_at)
            folder, _, name = item.relative.rpartition("/")
            tracks.append(
                models.AudioTrack(
                    id=item.id,
                    name=name,
                    folder=folder,
                    size_bytes=item.size,
                    playable=item.suffix in AUDIO_TYPES,
                    position=saved.position if saved is not None else 0,
                    duration=saved.total if saved is not None else None,
                )
            )
        return models.AudioOut(
            state="ready" if tracks else "empty",
            copy_id=row.id,
            tracks=tracks,
            complete=complete,
            last_track_id=latest[0] if latest else None,
        )

    def _progress(self, work_id: str, kind: str) -> dict[str, Row[Any]]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(media_progress).where(
                    media_progress.c.work_id == work_id, media_progress.c.kind == kind
                )
            ).all()
        return {row.resource_id: row for row in rows}

    def _stamp(self, copy_id: str, file_id: str, suffixes: set[str]) -> tuple[Row[Any], str]:
        row = self._ordinary_copy(copy_id)
        files, _complete = self.files(copy_id, Path(row.root_path), suffixes)
        match = next((item for item in files if item.id == file_id), None)
        if match is None:
            raise AtlasError("media_not_found", "找不到这个文件。", status=404)
        return row, match.stamp

    def save_progress(
        self,
        copy_id: str,
        file_id: str,
        kind: str,
        position: float,
        total: float | None,
        suffixes: set[str],
    ) -> None:
        row, stamp = self._stamp(copy_id, file_id, suffixes)
        values = {
            "work_id": row.work_id,
            "kind": kind,
            "position": position,
            "total": total,
            "stamp": stamp,
            "updated_at": _now(),
        }
        with writing(self._engine).begin() as connection:
            connection.execute(
                insert(media_progress)
                .values(resource_id=file_id, **values)
                .on_conflict_do_update(index_elements=[media_progress.c.resource_id], set_=values)
            )

    # --- bookmarks ---

    def bookmarks(self, work_id: str, kind: str) -> models.BookmarksOut:
        with self._engine.connect() as connection:
            get_ordinary_work(connection, work_id)
            rows = connection.execute(
                select(media_bookmarks)
                .where(media_bookmarks.c.work_id == work_id, media_bookmarks.c.kind == kind)
                .order_by(media_bookmarks.c.created_at)
            ).all()
        return models.BookmarksOut(
            bookmarks=[
                models.BookmarkOut(
                    id=row.id,
                    resource_id=row.resource_id,
                    position=row.position,
                    label=row.label,
                    created_at=row.created_at,
                )
                for row in rows
            ]
        )

    def add_bookmark(self, body: models.BookmarkIn, kind: str, suffixes: set[str]) -> str:
        row, stamp = self._stamp(body.copy_id, body.resource_id, suffixes)
        bookmark_id = uuid.uuid4().hex
        with writing(self._engine).begin() as connection:
            connection.execute(
                media_bookmarks.insert().values(
                    id=bookmark_id,
                    work_id=row.work_id,
                    kind=kind,
                    resource_id=body.resource_id,
                    position=body.position,
                    label=(body.label or "").strip() or None,
                    stamp=stamp,
                    created_at=_now(),
                )
            )
        return str(row.work_id)

    def remove_bookmark(self, bookmark_id: str) -> None:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(media_bookmarks).where(media_bookmarks.c.id == bookmark_id)
            ).first()
            if row is None:
                return
            get_ordinary_work(connection, row.work_id)
        with writing(self._engine).begin() as connection:
            connection.execute(delete(media_bookmarks).where(media_bookmarks.c.id == bookmark_id))

    # --- playlists ---

    def playlists(self) -> models.PlaylistsOut:
        """Only tracks of works in ordinary views, in the order the user chose. A track whose file
        has gone stays in the list, marked, and keeps its place."""
        with self._engine.connect() as connection:
            lists = connection.execute(select(playlists).order_by(playlists.c.created_at)).all()
            items = connection.execute(
                select(playlist_items).order_by(playlist_items.c.position)
            ).all()
            visible = {
                work_id
                for work_id in {entry.work_id for entry in items}
                if self._is_ordinary(connection, work_id)
            }
        return models.PlaylistsOut(
            playlists=[
                models.PlaylistOut(
                    id=item.id,
                    name=item.name,
                    items=[
                        models.PlaylistItem(
                            copy_id=entry.copy_id,
                            track_id=entry.track_id,
                            work_id=entry.work_id,
                            name=entry.name,
                        )
                        for entry in items
                        if entry.playlist_id == item.id and entry.work_id in visible
                    ],
                )
                for item in lists
            ]
        )

    @staticmethod
    def _is_ordinary(connection: Any, work_id: str) -> bool:
        try:
            get_ordinary_work(connection, work_id)
        except AtlasError:
            return False
        return True

    def save_playlist(self, body: models.PlaylistIn) -> models.PlaylistsOut:
        playlist_id = body.id or uuid.uuid4().hex
        with self._engine.connect() as connection:
            for item in body.items:
                get_ordinary_work(connection, item.work_id)
        with writing(self._engine).begin() as connection:
            existing = connection.execute(
                select(playlists.c.id).where(playlists.c.id == playlist_id)
            ).first()
            if existing is None:
                connection.execute(
                    playlists.insert().values(id=playlist_id, name=body.name, created_at=_now())
                )
            else:
                connection.execute(
                    update(playlists).where(playlists.c.id == playlist_id).values(name=body.name)
                )
            connection.execute(
                delete(playlist_items).where(playlist_items.c.playlist_id == playlist_id)
            )
            for position, item in enumerate(body.items):
                connection.execute(
                    playlist_items.insert().values(
                        playlist_id=playlist_id,
                        position=position,
                        copy_id=item.copy_id,
                        track_id=item.track_id,
                        work_id=item.work_id,
                        name=item.name,
                    )
                )
        return self.playlists()

    def remove_playlist(self, playlist_id: str) -> models.PlaylistsOut:
        with writing(self._engine).begin() as connection:
            connection.execute(
                delete(playlist_items).where(playlist_items.c.playlist_id == playlist_id)
            )
            connection.execute(delete(playlists).where(playlists.c.id == playlist_id))
        return self.playlists()
