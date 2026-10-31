"""Finding where a game keeps its saves, for the user to confirm. It never decides for them.

Two sources. The game's own files suggest places by engine. And playing tells the rest: after a
session, the files changed since it began, in the places programs write to, are looked at by name,
time and size only, never opened. Other programs write there too, so what is found is scored and
shown as suggestions. Nothing becomes a save rule, or gets backed up or uploaded, until the user
accepts it, because a confident wrong answer would look like a backup and not be one.
"""

import json
import logging
import os
import re
import threading
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import Engine, Row, select
from sqlalchemy.dialects.sqlite import insert

from app.adapters.system.registry import Registry, RegistryRefused, player_values
from app.api import models
from app.db.engine import writing
from app.db.schema import local_copies, save_discoveries
from app.domain.save_hints import EngineFacts, KnownFolders, read_facts
from app.repositories.works import get_ordinary_work
from app.services.game_updates import GameUpdater

logger = logging.getLogger("atlas")

MAX_ENTRIES = 600_000
_MAX_DEPTH = 9
_MAX_SHOWN = 8
_MAX_SAMPLE = 5
_SLACK_SECONDS = 3.0
_LIKELY_SCORE = 3
_SKIPPED = {
    "temp",
    "tmp",
    "cache",
    "caches",
    "cache2",
    "gpucache",
    "code cache",
    "shadercache",
    "dawncache",
    "grshadercache",
    "d3dscache",
    "crashes",
    "crash reports",
    "crashdumps",
    "logs",
    "log",
    "blob_storage",
    "microsoft",
    "packages",
    "google",
    "mozilla",
    "opera software",
    "bravesoftware",
    "nvidia",
    "nvidia corporation",
    "amd",
    "intel",
    "discord",
    "slack",
    "telegram desktop",
    "tencent",
    "npm",
    "npm-cache",
    "pip",
    "python",
    "uv",
    "code",
    "cursor",
    "jetbrains",
    "steam",
    "docker",
    "github",
    "github desktop",
    "anthropic",
    "claude",
    "claude-cli-nodejs",
    "libraryatlas",
    "dlsitenest",
    "connecteddevicesplatform",
    "squirreltemp",
    "unity",
    "onedrive",
    "node_modules",
    ".git",
    ".venv",
    "__pycache__",
}
_NOISE_EXTENSIONS = {
    ".log",
    ".tmp",
    ".temp",
    ".dmp",
    ".etl",
    ".lock",
    ".lnk",
    ".exe",
    ".dll",
    ".pdb",
    ".crdownload",
}
_NOISE_NAMES = re.compile(r"^(player(-prev)?\.log|output_log\.txt|desktop\.ini|thumbs\.db)$", re.I)
_SAVE_WORD = re.compile(r"(?<![a-z])(save|saves|savedata|savegame|sav|slot|profile|progress)", re.I)
_SAVE_EXTENSIONS = {
    ".sav",
    ".save",
    ".rpgsave",
    ".rmmzsave",
    ".rvdata2",
    ".rvdata",
    ".rxdata",
    ".lsd",
    ".ksd",
    ".kdt",
    ".es3",
}
_CONFIG_WORD = re.compile(r"(config|setting|option|preference|keybind|input|graphics)", re.I)
_DIGITS = re.compile(r"\d+")
# What a program may be called with no bearing on which game it is.
_GENERIC_NAMES = {"game", "games", "start", "launcher", "main", "play", "player", "application"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _norm(text: str | None) -> str:
    cleaned = unicodedata.normalize("NFKC", text or "").casefold()
    return re.sub(r"[\s\W_]+", "", cleaned)


@dataclass
class _Group:
    kind: str
    path: str
    files: list[tuple[str, int, float]] = field(default_factory=list)

    def add(self, name: str, size: int, modified: float) -> None:
        self.files.append((name, size, modified))


def _changed_since(
    base: Path, since: float, budget: list[int], stop: threading.Event
) -> list[tuple[Path, int, float]]:
    """Files under a place, changed since then. Names and times only; links are not followed."""
    found: list[tuple[Path, int, float]] = []
    stack: list[tuple[str, int]] = [(str(base), 0)]
    while stack:
        if stop.is_set():
            return found
        folder, depth = stack.pop()
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    budget[0] -= 1
                    if budget[0] < 0:
                        return found
                    if entry.is_symlink() or entry.is_junction():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if depth < _MAX_DEPTH and entry.name.casefold() not in _SKIPPED:
                            stack.append((entry.path, depth + 1))
                        continue
                    info = entry.stat(follow_symlinks=False)
                    if info.st_mtime < since:
                        continue
                    suffix = os.path.splitext(entry.name)[1].casefold()
                    if suffix in _NOISE_EXTENSIONS or _NOISE_NAMES.match(entry.name):
                        continue
                    found.append((Path(entry.path), info.st_size, info.st_mtime))
        except OSError:
            continue
    return found


def _group_outside(path: Path, base: Path) -> str | None:
    """The folder a suggestion should name: the program's own, not one file, not all of AppData."""
    parts = path.relative_to(base).parts
    if len(parts) < 2:
        return None
    depth = 2 if len(parts) > 2 else 1
    if parts[0].casefold() == "my games" and len(parts) > 2:
        depth = 2
    return str(base.joinpath(*parts[:depth]))


def _pattern_of(name: str) -> str:
    """`Save03.rvdata2` becomes `Save*.rvdata2`, so slots not yet used are covered too."""
    stem, suffix = os.path.splitext(name)
    if _DIGITS.search(stem):
        return f"{_DIGITS.sub('*', stem, count=1)}{suffix}"
    return name


def score(group: _Group, tokens: list[str]) -> tuple[int, str]:
    """How much this looks like the game's saves, and why, in the user's words. Only the end of a
    path is read for names: the user's own name higher up says nothing about the game."""
    points = 0
    reasons: list[str] = []
    path_key = _norm("".join(Path(group.path).parts[-2:]))
    if group.kind == "inside":
        points += 2
        reasons.append("在游戏文件夹里")
    if any(
        len(token) >= 4 and token not in _GENERIC_NAMES and token in path_key for token in tokens
    ):
        points += 3
        reasons.append("路径里有这部游戏的名字")
    names = [item[0] for item in group.files]
    place = "/".join(Path(group.path).parts[-2:])
    if _SAVE_WORD.search(place) or any(_SAVE_WORD.search(name) for name in names):
        points += 2
        reasons.append("名字像存档")
    if any(os.path.splitext(name)[1].casefold() in _SAVE_EXTENSIONS for name in names):
        points += 2
        reasons.append("文件类型像存档")
    if names and all(_CONFIG_WORD.search(name) for name in names):
        points -= 2
        reasons.append("可能只是设置")
    return points, "、".join(reasons) or "这段时间内有变化"


class SaveDiscovery:
    def __init__(
        self,
        engine: Engine,
        updater: GameUpdater,
        folders: KnownFolders,
        registry: Registry,
        *,
        in_use: Callable[[Path], bool] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._engine = engine
        self._updater = updater
        self._folders = folders
        self._registry = registry
        self._in_use = in_use or updater.is_running
        self._sleep = sleep
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: dict[str, threading.Thread] = {}
        # Seconds to see the game start, between looks, and for it to finish writing afterwards.
        self.watch_times = (30.0, 5.0, 10.0)

    def recover(self) -> None:
        """A scan cut off by a restart can simply be run again."""
        with writing(self._engine).begin() as connection:
            connection.execute(
                save_discoveries.update()
                .where(save_discoveries.c.state == "scanning")
                .values(state="recording")
            )

    def shutdown(self) -> None:
        self._stop.set()
        for thread in list(self._threads.values()):
            thread.join(timeout=10)

    # --- what is known ---

    def _copy(self, work_id: str) -> tuple[Row[Any], Row[Any] | None]:
        with self._engine.connect() as connection:
            work = get_ordinary_work(connection, work_id)
            copy = connection.execute(
                select(local_copies)
                .where(local_copies.c.work_id == work_id)
                .order_by(local_copies.c.is_default.desc(), local_copies.c.created_at)
                .limit(1)
            ).first()
        return work, copy

    def _row(self, work_id: str) -> Row[Any] | None:
        with self._engine.connect() as connection:
            return connection.execute(
                select(save_discoveries).where(save_discoveries.c.work_id == work_id)
            ).first()

    def _save(self, work_id: str, **values: Any) -> None:
        with writing(self._engine).begin() as connection:
            connection.execute(
                insert(save_discoveries)
                .values(work_id=work_id, **values)
                .on_conflict_do_update(index_elements=[save_discoveries.c.work_id], set_=values)
            )

    def _measure(
        self, kind: str, path: str, root: Path
    ) -> tuple[int, int, float | None, list[str]]:
        if kind == "registry":
            try:
                values = self._registry.read(path)
            except (RegistryRefused, OSError):
                return 0, 0, None, []
            return player_values(values), 0, None, []
        rule = {"kind": kind, "path": path}
        try:
            files = self._updater.rule_files(rule, root)
        except (OSError, ValueError):
            return 0, 0, None, []
        size = 0
        latest: float | None = None
        names: list[str] = []
        for _relative, file, _single in files[:20_000]:
            try:
                info = file.stat()
            except OSError:
                continue
            size += info.st_size
            latest = max(latest or 0.0, info.st_mtime)
            if len(names) < _MAX_SAMPLE:
                names.append(file.name)
        return len(files), size, latest, names

    def suggestions(self, work_id: str) -> models.SaveSuggestionsOut:
        _work, copy = self._copy(work_id)
        row = self._row(work_id)
        session = models.SaveSessionOut(
            state=row.state if row else "none",
            started_at=row.started_at if row else None,
            finished_at=row.finished_at if row else None,
            complete=bool(row.complete) if row else True,
        )
        if copy is None or not Path(copy.root_path).is_dir():
            return models.SaveSuggestionsOut(
                available=False, engine=None, suggestions=[], session=session
            )
        root = Path(copy.root_path)
        facts = read_facts(root, self._folders)
        current = {
            (rule.kind, rule.path.casefold()) for rule in self._updater.save_config(work_id).rules
        }
        listed: dict[tuple[str, str], models.SaveSuggestion] = {}
        played = json.loads(row.results) if row and row.results else []
        for item in played:
            kind, path = item["kind"], item["path"]
            count, size, latest, names = self._measure(kind, path, root)
            listed[(kind, path.casefold())] = models.SaveSuggestion(
                kind=cast(models.SaveRuleKind, kind),
                path=path,
                source="play",
                reason=item["reason"],
                likely=bool(item["likely"]),
                files=count,
                size_bytes=size,
                modified_at=datetime.fromtimestamp(latest, UTC).isoformat() if latest else None,
                samples=names,
                configured=(kind, path.casefold()) in current,
            )
        for hint in facts.hints:
            key = (hint.kind, hint.path.casefold())
            count, size, latest, names = self._measure(hint.kind, hint.path, root)
            if count == 0:
                continue  # Only what is really there. Asking about an empty guess helps nobody.
            if key in listed:
                listed[key] = listed[key].model_copy(
                    update={"likely": True, "reason": f"{listed[key].reason}、{hint.reason}"}
                )
                continue
            listed[key] = models.SaveSuggestion(
                kind=cast(models.SaveRuleKind, hint.kind),
                path=hint.path,
                source="engine",
                reason=hint.reason,
                likely=True,
                files=count,
                size_bytes=size,
                modified_at=datetime.fromtimestamp(latest, UTC).isoformat() if latest else None,
                samples=names,
                configured=key in current,
            )
        ordered = sorted(
            listed.values(), key=lambda item: (not item.likely, item.source != "play", item.path)
        )
        return models.SaveSuggestionsOut(
            available=True, engine=facts.engine, suggestions=ordered, session=session
        )

    # --- a session of play ---

    def start_session(self, work_id: str) -> models.SaveSuggestionsOut:
        """From now on, what changes is what the game does. It need not be started from Atlas."""
        self._copy(work_id)
        self._save(
            work_id,
            state="recording",
            started_at=_now(),
            started_clock=time.time(),
            finished_at=None,
            results=None,
            complete=1,
        )
        return self.suggestions(work_id)

    def game_started(self, work_id: str, program: Path) -> None:
        """Only for a game whose saves are not settled, and the scan runs once it has closed."""
        config = self._updater.save_config(work_id)
        if config.rules or config.confirmed_none:
            return
        self.start_session(work_id)
        thread = threading.Thread(
            target=self._watch, args=(work_id, program), name="save-watch", daemon=True
        )
        self._threads[f"watch-{work_id}"] = thread
        thread.start()

    def _watch(self, work_id: str, program: Path) -> None:
        see_start, between, calm = self.watch_times
        waited = 0.0
        # A launcher that hands over is never seen running: the user says when they are done.
        while not self._in_use(program):
            if waited >= see_start or self._stop.is_set():
                return
            self._sleep(between)
            waited += between
        while self._in_use(program):
            if self._stop.is_set():
                return
            self._sleep(between)
        self._sleep(calm)
        self.finish_session(work_id)

    def finish_session(self, work_id: str) -> models.SaveSuggestionsOut:
        _work, copy = self._copy(work_id)
        row = self._row(work_id)
        if row is None or copy is None or row.state == "scanning":
            return self.suggestions(work_id)
        self._save(work_id, state="scanning")
        thread = threading.Thread(target=self._scan, args=(work_id,), name="save-scan", daemon=True)
        self._threads[f"scan-{work_id}"] = thread
        thread.start()
        return self.suggestions(work_id)

    def _scan(self, work_id: str) -> None:
        try:
            self._save(work_id, **self._scan_results(work_id), state="done", finished_at=_now())
        except Exception as error:  # noqa: BLE001 - must end the state; type only, no paths.
            logger.error("save scan failed: %s", type(error).__name__)
            self._save(work_id, state="failed", finished_at=_now())

    def _scan_results(self, work_id: str) -> dict[str, Any]:
        work, copy = self._copy(work_id)
        row = self._row(work_id)
        assert row is not None and copy is not None
        since = float(row.started_clock) - _SLACK_SECONDS
        root = Path(copy.root_path)
        facts: EngineFacts = read_facts(root, self._folders)
        tokens = [
            _norm(value)
            for value in (work.title, facts.company, facts.product, facts.project, root.name)
        ]
        program = Path(copy.entry_path).stem if copy.entry_path else None
        tokens.append(_norm(program))
        budget = [MAX_ENTRIES]
        groups: dict[tuple[str, str], _Group] = {}

        def add(kind: str, path: str, file: Path, size: int, modified: float) -> None:
            groups.setdefault((kind, path.casefold()), _Group(kind, path)).add(
                file.name, size, modified
            )

        for file, size, modified in _changed_since(root, since, budget, self._stop):
            parent = file.parent.relative_to(root).as_posix()
            if parent == ".":
                add("inside", _pattern_of(file.name), file, size, modified)
            else:
                add("inside", parent, file, size, modified)
        for base in self._folders.roots():
            if not base.is_dir() or base.resolve().is_relative_to(root.resolve()):
                continue
            for file, size, modified in _changed_since(base, since, budget, self._stop):
                if file.is_relative_to(root):
                    continue
                folder = _group_outside(file, base)
                if folder:
                    add("outside", folder, file, size, modified)
        results: list[dict[str, Any]] = []
        for group in groups.values():
            points, reason = score(group, tokens)
            results.append(
                {
                    "kind": group.kind,
                    "path": group.path,
                    "reason": reason,
                    "likely": points >= _LIKELY_SCORE,
                    "points": points,
                }
            )
        for hint in facts.hints:
            if hint.kind != "registry":
                continue
            changed = None
            try:
                changed = self._registry.changed_at(hint.path)
                filled = player_values(self._registry.read(hint.path))
            except (RegistryRefused, OSError):
                continue
            if changed is not None and filled and changed.timestamp() >= since:
                results.append(
                    {
                        "kind": "registry",
                        "path": hint.path,
                        "reason": "这次游戏时写入了注册表",
                        "likely": True,
                        "points": 9,
                    }
                )
        results.sort(key=lambda item: -int(item["points"]))
        return {
            "results": json.dumps(results[:_MAX_SHOWN], ensure_ascii=False),
            "complete": 1 if budget[0] >= 0 else 0,
        }
