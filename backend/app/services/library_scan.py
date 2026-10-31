"""Finds the user's work folders on their drives and matches them to the library.

Reads folder names only: no file is opened, moved, changed or run, and nothing in a folder decides
what gets executed. It runs in the background, within a budget: at startup, after a sync and when
asked. The user's decision (2026-10-31) is that a clear match links by itself, so only links are
written, each can be undone, and what they take back is not linked again unless they ask. An
ambiguous match is never picked for them.
"""

import difflib
import json
import logging
import os
import re
import threading
import unicodedata
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import Engine, Row, delete, func, select, update

from app.adapters.system.volumes import Volume, list_volumes
from app.api import models
from app.core.errors import AtlasError
from app.db.engine import writing
from app.db.schema import local_copies, personal_records, scan_items, scan_jobs, scan_roots, works
from app.repositories.works import ORDINARY
from app.services.local_copies import LocalCopies

logger = logging.getLogger("atlas")

_KIND_FOLDERS = ("Game", "Audio", "Comic", "Illust", "Movie", "Other")
# Where the user's library is, on whichever drive (user's statement, 2026-10-31).
_KNOWN_PLACES = ("DLsiteNest/Library",)
_ROOT_NAMES = {"library"}
_ROOT_PARENT_NAMES = {"dlsitenest"}
_SKIPPED = {
    "windows",
    "program files",
    "program files (x86)",
    "programdata",
    "$recycle.bin",
    "system volume information",
    "recovery",
    "appdata",
    "node_modules",
    ".git",
    ".venv",
    "$windows.~bt",
    "$windows.~ws",
    "msocache",
    "perflogs",
}
# `Title ver121`, `Title_v1.2.3`, `Title (Ver.1.21)`: the release, not part of the name. Only at the
# end, and only with the word: a bare number may be another volume.
_VERSION = re.compile(
    r"[\s_\-–—~～(\[（【]*(?<![a-z0-9])(?:version|ver|v)[\s._]*\d+(?:[._]\d+)*[a-z]?[\s)\]）】]*$",
    re.IGNORECASE,
)
_ID = re.compile(r"(?<![A-Za-z0-9])((?:RJ|VJ|BJ)\d{6,8})(?![0-9])", re.IGNORECASE)
_DEEP_DEPTH = 6
MAX_FOLDERS = 400_000
_PROGRESS_EVERY = 500
_ACTIVE = ("running",)
_PAGE_LIMIT = 200
# Long enough that a same name is not a coincidence.
_MIN_UNIQUE_TITLE = 6
_MIN_CONTAINED_TITLE = 8
# How alike two names by the same maker must be: to be the same work, and to be worth asking about.
_SAME_NAME = 0.85
_SIMILAR_NAME = 0.6
_MAX_CANDIDATES = 3
MESSAGES = {
    "budget": "这次扫描到达了文件夹数量上限，范围没有查完，可以指定具体文件夹再扫。",
    "interrupted": "上次扫描被中断了，已发现的结果还在，可以重新扫描。",
    "cancelled": "扫描已取消，已发现的结果还在。",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _norm(text: str | None) -> str:
    """For comparing names: full-width forms, case and punctuation do not count."""
    cleaned = unicodedata.normalize("NFKC", text or "").casefold()
    return re.sub(r"[\s\W_]+", "", cleaned)


def _without_version(name: str) -> str:
    return _VERSION.sub("", name).strip() or name


def _key(path: Path | str) -> str:
    return str(path).casefold()


def _is_link(entry: os.DirEntry[str]) -> bool:
    return entry.is_symlink() or entry.is_junction()


def _subfolders(path: Path | str) -> Iterator[os.DirEntry[str]]:
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                try:
                    if not _is_link(entry) and entry.is_dir(follow_symlinks=False):
                        yield entry
                except OSError:
                    continue
    except OSError:
        return


def looks_like_library(path: Path) -> bool:
    """`<type>/<maker>/<title>`: the layout seen in the user's own libraries. A folder merely
    named Game is not enough: it must hold that depth, and either be named like a library or
    hold more than one type. Anything else stays unrecognized."""
    kinds = [path / name for name in _KIND_FOLDERS if (path / name).is_dir()]
    deep = 0
    for kind in kinds:
        for maker in _subfolders(kind):
            if next(_subfolders(maker.path), None) is not None:
                deep += 1
                break
    if not deep:
        return False
    named = path.name.casefold() in _ROOT_NAMES or path.parent.name.casefold() in _ROOT_PARENT_NAMES
    return named or deep >= 2


def _contained(title_key: str, same_maker: list[Row[Any]]) -> list[Row[Any]]:
    """Works by this maker whose name holds the folder's, or the other way round: a subtitle left
    off. A number in what is left over means another volume, so that is no match."""
    found = []
    for row in same_maker:
        short, long = sorted((title_key, _norm(row.title)), key=len)
        if len(short) < _MIN_CONTAINED_TITLE or short not in long:
            continue
        if not any(character.isdigit() for character in long.replace(short, "", 1)):
            found.append(row)
    return found


def _similar(title_key: str, same_maker: list[Row[Any]]) -> list[tuple[float, Row[Any]]]:
    """Works by this maker with a name like the folder's, closest first."""
    scored = [
        (difflib.SequenceMatcher(None, title_key, _norm(row.title)).ratio(), row)
        for row in same_maker
    ]
    return sorted((item for item in scored if item[0] >= _SIMILAR_NAME), key=lambda item: -item[0])


@dataclass
class _Control:
    cancelled: threading.Event


class LibraryScanner:
    def __init__(
        self,
        engine: Engine,
        copies: LocalCopies,
        volumes: Callable[[], list[Volume]] = list_volumes,
    ) -> None:
        self._engine = engine
        self._copies = copies
        self._volumes = volumes
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()

    def recover(self) -> None:
        with writing(self._engine).begin() as connection:
            connection.execute(
                update(scan_jobs)
                .where(scan_jobs.c.state.in_(_ACTIVE))
                .values(state="interrupted", code="interrupted", finished_at=_now())
            )

    def shutdown(self) -> None:
        self._cancel.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    # --- reading ---

    def status(self) -> models.ScanStatus:
        with self._engine.connect() as connection:
            job = connection.execute(
                select(scan_jobs).order_by(scan_jobs.c.started_at.desc()).limit(1)
            ).first()
            roots = connection.execute(select(scan_roots).order_by(scan_roots.c.path)).all()
            counts = dict(
                connection.execute(
                    select(scan_items.c.state, func.count()).group_by(scan_items.c.state)
                )
                .tuples()
                .all()
            )
        return models.ScanStatus(
            volumes=[models.VolumeOut(**volume.__dict__) for volume in self._volumes()],
            job=self._job(job) if job else None,
            roots=[
                models.ScanRootOut(
                    id=row.id,
                    path=row.path,
                    active=bool(row.active),
                    available=Path(row.path).is_dir(),
                    last_scanned_at=row.last_scanned_at,
                )
                for row in roots
            ],
            counts=models.ScanCounts(
                certain=counts.get("certain", 0),
                likely=counts.get("likely", 0),
                review=counts.get("review", 0),
                unmatched=counts.get("unmatched", 0),
                linked=counts.get("linked", 0),
                ignored=counts.get("ignored", 0),
            ),
        )

    @staticmethod
    def _job(row: Row[Any]) -> models.ScanJobOut:
        return models.ScanJobOut(
            id=row.id,
            state=cast(models.ScanState, row.state),
            folders=row.folders,
            found=row.found,
            skipped=row.skipped,
            complete=bool(row.complete),
            code=row.code,
            message=MESSAGES.get(row.code) if row.code else None,
            started_at=row.started_at,
            finished_at=row.finished_at,
            auto_linked=row.auto_linked,
            batch_id=row.batch_id,
        )

    def items(
        self, state: models.ScanItemState | None, offset: int, limit: int
    ) -> models.ScanItemsOut:
        conditions = [scan_items.c.state == state] if state else []
        with self._engine.connect() as connection:
            total = connection.execute(
                select(func.count()).select_from(scan_items).where(*conditions)
            ).scalar_one()
            rows = connection.execute(
                select(scan_items)
                .where(*conditions)
                .order_by(scan_items.c.maker_key, scan_items.c.title_key, scan_items.c.id)
                .offset(offset)
                .limit(min(limit, _PAGE_LIMIT))
            ).all()
            titles = dict(
                connection.execute(
                    select(works.c.id, works.c.title)
                    .join(personal_records, personal_records.c.work_id == works.c.id)
                    .where(
                        ORDINARY,
                        works.c.id.in_(
                            {work for row in rows for work in json.loads(row.candidates or "[]")}
                        ),
                    )
                )
                .tuples()
                .all()
            )
        return models.ScanItemsOut(
            total=total,
            items=[
                models.ScanItemOut(
                    id=row.id,
                    path=row.path,
                    kind_folder=row.kind_folder,
                    maker=row.maker,
                    title=row.title,
                    state=cast(models.ScanItemState, row.state),
                    reason=row.reason,
                    candidates=[
                        models.ScanCandidate(work_id=work, title=titles[work])
                        for work in json.loads(row.candidates or "[]")
                        if work in titles
                    ],
                )
                for row in rows
            ],
        )

    # --- scanning ---

    def start(self, body: models.ScanStart) -> models.ScanStatus:
        volumes = {volume.letter: volume for volume in self._volumes()}
        for letter in body.drives:
            volume = volumes.get(letter.upper())
            # Network shares are never walked on their own: a named folder is the user's choice.
            if volume is None or volume.kind == "network" or not volume.available:
                raise AtlasError("scan_invalid", "不能扫描这个盘。", status=422)
        roots = [Path(raw.strip()) for raw in body.roots]
        for root in roots:
            if not root.is_absolute() or not root.is_dir():
                raise AtlasError("scan_invalid", "这个文件夹不存在。", status=422)
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self.status()
            self._cancel.clear()
            job_id = uuid.uuid4().hex
            with writing(self._engine).begin() as connection:
                connection.execute(
                    scan_jobs.insert().values(id=job_id, state="running", started_at=_now())
                )
            self._thread = threading.Thread(
                target=self._run,
                args=(
                    job_id,
                    [letter.upper() for letter in body.drives],
                    roots,
                    body.deep,
                    body.auto_link,
                ),
                name="library-scan",
                daemon=True,
            )
            self._thread.start()
        return self.status()

    def scan_automatically(self) -> None:
        """Looks in the known place on each fixed drive and links what clearly matches. Must not
        disturb whatever called it, and a test library has no drives, so it does nothing there."""
        try:
            drives = [
                volume.letter
                for volume in self._volumes()
                if volume.kind == "fixed" and volume.available
            ]
            if drives:
                self.start(models.ScanStart(drives=drives, auto_link=True))
        except Exception as error:  # noqa: BLE001 - type only, no paths.
            logger.error("automatic library scan failed: %s", type(error).__name__)

    def cancel(self) -> models.ScanStatus:
        self._cancel.set()
        return self.status()

    def _report(self, job_id: str, **values: Any) -> None:
        with writing(self._engine).begin() as connection:
            connection.execute(update(scan_jobs).where(scan_jobs.c.id == job_id).values(**values))

    def _run(
        self, job_id: str, drives: list[str], named: list[Path], deep: bool, auto_link: bool
    ) -> None:
        stats = {"folders": 0, "found": 0, "skipped": 0}
        complete = True
        try:
            libraries: dict[str, Path] = {}
            for root in [*named, *self._saved_roots()]:
                if looks_like_library(root):
                    libraries[_key(root.resolve())] = root.resolve()
                elif root in named:
                    # A folder the user named, with no library at its top: look inside it.
                    complete &= self._walk(root, libraries, stats, job_id)
            for letter in drives:
                base = Path(f"{letter}:\\")
                for place in _KNOWN_PLACES:
                    candidate = base / place
                    if candidate.is_dir() and looks_like_library(candidate):
                        libraries[_key(candidate.resolve())] = candidate.resolve()
                if deep:
                    complete &= self._walk(base, libraries, stats, job_id)
            for root in libraries.values():
                if self._cancel.is_set():
                    break
                self._read_library(root, stats, job_id)
            if self._cancel.is_set():
                self._report(
                    job_id,
                    state="cancelled",
                    code="cancelled",
                    complete=0,
                    finished_at=_now(),
                    **stats,
                )
                return
            linked: dict[str, Any] = self._link_matches(job_id) if auto_link else {}
            self._report(
                job_id,
                state="done",
                complete=1 if complete else 0,
                code=None if complete else "budget",
                finished_at=_now(),
                **linked,
                **stats,
            )
        except Exception as error:  # noqa: BLE001 - must end the job; type only, no paths.
            logger.error("library scan failed: %s", type(error).__name__)
            self._report(job_id, state="failed", code="failed", finished_at=_now(), **stats)

    def _saved_roots(self) -> list[Path]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(scan_roots.c.path).where(scan_roots.c.active == 1)
            ).all()
        return [Path(row.path) for row in rows if Path(row.path).is_dir()]

    def _walk(
        self, base: Path, libraries: dict[str, Path], stats: dict[str, int], job_id: str
    ) -> bool:
        """Folder names only, down a limited depth. Links are never followed, so it cannot leave
        the chosen place or go in circles, and a library found is not walked into. False if the
        budget ran out before everything was seen."""
        stack: list[tuple[str, int]] = [(str(base), 0)]
        while stack:
            if self._cancel.is_set():
                return False
            if stats["folders"] >= MAX_FOLDERS:
                return False
            folder, depth = stack.pop()
            try:
                entries = list(_subfolders(folder))
            except OSError:
                stats["skipped"] += 1
                continue
            for entry in entries:
                if entry.name.casefold() in _SKIPPED:
                    continue
                stats["folders"] += 1
                if stats["folders"] % _PROGRESS_EVERY == 0:
                    self._report(job_id, **stats)
                path = Path(entry.path)
                if looks_like_library(path):
                    libraries[_key(path.resolve())] = path.resolve()
                elif depth + 1 < _DEEP_DEPTH:
                    stack.append((entry.path, depth + 1))
        return True

    # --- matching ---

    def _index(
        self,
    ) -> tuple[dict[str, str], dict[str, list[Row[Any]]], dict[str, list[Row[Any]]]]:
        """Ordinary works only: a hidden one must not be revealed by a folder that matches it."""
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(works.c.id, works.c.source_work_id, works.c.title, works.c.maker)
                .join(personal_records, personal_records.c.work_id == works.c.id)
                .where(ORDINARY, works.c.source_id == "dlsite")
            ).all()
        by_id = {row.source_work_id.upper(): row.id for row in rows}
        by_title: dict[str, list[Row[Any]]] = {}
        by_maker: dict[str, list[Row[Any]]] = {}
        for row in rows:
            by_title.setdefault(_norm(row.title), []).append(row)
            by_maker.setdefault(_norm(row.maker), []).append(row)
        return by_id, by_title, by_maker

    @staticmethod
    def _match(
        names: list[str],
        maker: str,
        title: str,
        by_id: dict[str, str],
        by_title: dict[str, list[Row[Any]]],
        by_maker: dict[str, list[Row[Any]]],
    ) -> tuple[str, list[str], str]:
        for name in names:
            found = _ID.search(name)
            if found and found.group(1).upper() in by_id:
                return "certain", [by_id[found.group(1).upper()]], "文件夹名里有作品编号"
        # As it stands first: a work may really be called that. Then without the release.
        title_key = _norm(title)
        same = by_title.get(title_key, [])
        if not same:
            title_key = _norm(_without_version(title))
            same = by_title.get(title_key, [])
        if not same:
            contained = _contained(title_key, by_maker.get(_norm(maker), []))
            if len(contained) == 1:
                return "likely", [contained[0].id], "制作方相同，作品名只差副标题"
            similar = _similar(title_key, by_maker.get(_norm(maker), []))
            if similar:
                close = [row for score, row in similar if score >= _SAME_NAME]
                # Different numbers are different volumes, however alike the rest is.
                if len(close) == 1 and re.findall(r"\d+", _norm(close[0].title)) == re.findall(
                    r"\d+", title_key
                ):
                    return "likely", [close[0].id], "制作方相同，作品名几乎一样"
                return (
                    "review",
                    [row.id for _score, row in similar[:_MAX_CANDIDATES]],
                    "制作方相同，作品名相近",
                )
            return "unmatched", [], "作品库里没有同名作品"
        same_maker = [row for row in same if _norm(row.maker) == _norm(maker)]
        if len(same_maker) == 1:
            return "likely", [same_maker[0].id], "制作方和作品名都相同"
        if len(same) == 1:
            if len(title_key) >= _MIN_UNIQUE_TITLE:
                return "likely", [same[0].id], "作品名完全相同，且只有这一部"
            return "review", [same[0].id], "作品名很短且制作方不同"
        return "review", [row.id for row in same], "有多部同名作品"

    def _read_library(self, root: Path, stats: dict[str, int], job_id: str) -> None:
        """`<type>/<maker>/<title>`. A folder already seen keeps what the user decided about it."""
        by_id, by_title, by_maker = self._index()
        now = _now()
        with writing(self._engine).begin() as connection:
            row = connection.execute(
                select(scan_roots.c.id).where(scan_roots.c.path_key == _key(root))
            ).first()
            if row is None:
                root_id = uuid.uuid4().hex
                connection.execute(
                    scan_roots.insert().values(
                        id=root_id,
                        path=str(root),
                        path_key=_key(root),
                        active=1,
                        last_scanned_at=now,
                    )
                )
            else:
                root_id = row.id
                connection.execute(
                    update(scan_roots).where(scan_roots.c.id == root_id).values(last_scanned_at=now)
                )
            known = {
                item.path_key: item
                for item in connection.execute(
                    select(scan_items.c.path_key, scan_items.c.state).where(
                        scan_items.c.root_id == root_id
                    )
                )
            }
        batch: list[dict[str, Any]] = []
        for kind in _KIND_FOLDERS:
            kind_path = root / kind
            if not kind_path.is_dir():
                continue
            for maker in _subfolders(kind_path):
                if self._cancel.is_set():
                    break
                for title in _subfolders(maker.path):
                    stats["folders"] += 1
                    key = _key(title.path)
                    existing = known.get(key)
                    if existing is not None and existing.state in ("linked", "ignored"):
                        continue
                    state, candidates, reason = self._match(
                        [title.name, maker.name],
                        maker.name,
                        title.name,
                        by_id,
                        by_title,
                        by_maker,
                    )
                    batch.append(
                        {
                            "id": uuid.uuid4().hex,
                            "root_id": root_id,
                            "path": title.path,
                            "path_key": key,
                            "kind_folder": kind,
                            "maker": maker.name,
                            "maker_key": _norm(maker.name),
                            "title": title.name,
                            "title_key": _norm(title.name),
                            "state": state,
                            "reason": reason,
                            "candidates": json.dumps(candidates),
                            "job_id": job_id,
                        }
                    )
                    stats["found"] += 1
                    if len(batch) >= 200:
                        self._save(batch, known)
                        batch = []
                        self._report(job_id, **stats)
        self._save(batch, known)
        self._report(job_id, **stats)

    def _save(self, batch: list[dict[str, Any]], known: dict[str, Any]) -> None:
        """Short transactions, and the same folder is one row however often it is scanned."""
        if not batch:
            return
        with writing(self._engine).begin() as connection:
            for item in batch:
                if item["path_key"] in known:
                    values = {
                        name: value
                        for name, value in item.items()
                        if name not in ("id", "path_key", "root_id")
                    }
                    connection.execute(
                        update(scan_items)
                        .where(scan_items.c.path_key == item["path_key"])
                        .values(**values)
                    )
                else:
                    connection.execute(scan_items.insert().values(**item))

    # --- deciding ---

    def _item(self, item_id: str) -> Row[Any]:
        with self._engine.connect() as connection:
            row = connection.execute(select(scan_items).where(scan_items.c.id == item_id)).first()
        if row is None:
            raise AtlasError("scan_item_not_found", "找不到这条扫描结果。", status=404)
        return row

    def _link(self, row: Row[Any], work_id: str, batch_id: str) -> bool:
        path = Path(row.path)
        if not path.is_dir():
            return False
        self._copies.add_found(work_id, path, origin="scanned", batch_id=batch_id)
        with writing(self._engine).begin() as connection:
            connection.execute(
                update(scan_items)
                .where(scan_items.c.id == row.id)
                .values(state="linked", work_id=work_id, batch_id=batch_id, declined=0)
            )
        return True

    def _link_matches(self, job_id: str) -> dict[str, Any]:
        """What this scan found clearly, apart from what the user already took back. One folder
        that cannot be linked does not stop the others."""
        batch_id = uuid.uuid4().hex
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(scan_items).where(
                    scan_items.c.job_id == job_id,
                    scan_items.c.state.in_(("certain", "likely")),
                    scan_items.c.declined == 0,
                )
            ).all()
        linked = 0
        for row in rows:
            candidates = json.loads(row.candidates or "[]")
            try:
                if len(candidates) == 1 and self._link(row, candidates[0], batch_id):
                    linked += 1
            except AtlasError:
                continue
        return {"auto_linked": linked, "batch_id": batch_id if linked else None}

    def import_matches(self, body: models.ScanImport) -> models.ScanImportOut:
        """What the user chose to accept. One work with several folders gets several copies, and
        nothing is moved. Unavailable folders are left for next time, not treated as gone."""
        batch_id = uuid.uuid4().hex
        states = ["certain"]
        if body.include_likely:
            states.append("likely")
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(scan_items).where(scan_items.c.state.in_(states))
            ).all()
        linked = skipped = 0
        for row in rows:
            candidates = json.loads(row.candidates or "[]")
            if len(candidates) == 1 and self._link(row, candidates[0], batch_id):
                linked += 1
            else:
                skipped += 1
        return models.ScanImportOut(batch_id=batch_id, linked=linked, skipped=skipped)

    def link_item(self, item_id: str, work_id: str) -> models.ScanItemsOut:
        row = self._item(item_id)
        if work_id not in json.loads(row.candidates or "[]"):
            raise AtlasError("scan_invalid", "这部作品不是这个文件夹的候选。", status=422)
        if not self._link(row, work_id, uuid.uuid4().hex):
            raise AtlasError("scan_unavailable", "这个文件夹现在不可用。", status=409)
        return self.items(None, 0, 1)

    def ignore_item(self, item_id: str) -> models.ScanItemsOut:
        self._item(item_id)
        with writing(self._engine).begin() as connection:
            connection.execute(
                update(scan_items).where(scan_items.c.id == item_id).values(state="ignored")
            )
        return self.items(None, 0, 1)

    def undo(self, batch_id: str) -> models.ScanImportOut:
        """Takes back the links that import made. Nothing else, and never a file."""
        with writing(self._engine).begin() as connection:
            removed = connection.execute(
                delete(local_copies).where(
                    local_copies.c.batch_id == batch_id, local_copies.c.origin == "scanned"
                )
            ).rowcount
            connection.execute(
                update(scan_items)
                .where(scan_items.c.batch_id == batch_id)
                .values(state="likely", batch_id=None, work_id=None, declined=1)
            )
            connection.execute(
                update(scan_jobs)
                .where(scan_jobs.c.batch_id == batch_id)
                .values(auto_linked=0, batch_id=None)
            )
        return models.ScanImportOut(batch_id=batch_id, linked=-int(removed), skipped=0)

    def set_root_active(self, root_id: str, active: bool) -> models.ScanStatus:
        """Stops looking there. What was found and linked stays."""
        with writing(self._engine).begin() as connection:
            connection.execute(
                update(scan_roots)
                .where(scan_roots.c.id == root_id)
                .values(active=1 if active else 0)
            )
        return self.status()
