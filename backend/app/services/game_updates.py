"""Replaces a game's files with a new version, with its saves as the thing to protect.

The order is the safety: saves are backed up and that backup proven restorable before anything
else; the new version is unpacked beside the old one; only then are the two folders swapped, by
rename, and the saves moved across. The old folder is kept until the user says the new one is
good, because only playing it can show that. Each step is on record first, so a crash is undone
by looking at what is actually on disk.

Nothing here touches anything but the copy being updated, its saves as the user named them, and
what this task itself created. No other copy of the game is affected, and nothing is ever run.
"""

import hashlib
import json
import logging
import os
import shutil
import tempfile
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import Connection, Engine, Row, delete, select, update
from sqlalchemy.exc import IntegrityError

from app.adapters.system.archives import ArchiveProblem, Stopped, safe_parts
from app.api import models
from app.core.config import Settings
from app.core.errors import AtlasError
from app.db.engine import writing
from app.db.schema import game_updates, local_copies, save_backups, save_configs
from app.repositories.works import get_ordinary_work
from app.services.downloads import DownloadQueue
from app.services.extractions import ExtractionService
from app.services.folders import is_protected

logger = logging.getLogger("atlas")

_WORKING = ("queued", "backing_up", "downloading", "unpacking", "replacing", "cleaning")
_HOLDS_KEY = (*_WORKING, "awaiting_confirmation")
_KEEP_BACKUPS = 5
_HASH_BYTES = 1024 * 1024
_MAX_EXTRA_SAMPLE = 8
_MAX_WALK = 500_000
_POLL = 0.1
MESSAGES = {
    "saves_unconfirmed": "请先说明这部作品的存档在哪里，或确认没有需要保留的存档。",
    "confirm_closed": "请先确认游戏已经关闭。",
    "game_running": "主程序正在使用中。请关闭游戏后再更新，Atlas 不会强行结束它。",
    "no_entry": "请先选择主程序。Atlas 要靠它判断新文件是不是完整的游戏。",
    "copy_unavailable": "这个文件夹现在不可用，已停止。旧版本和存档都没有动。",
    "backup_failed": "存档备份没有通过校验，已停止。旧版本和存档都没有动。",
    "download_failed": "新版本下载没有完成，已停止。旧版本和存档都没有动。",
    "entry_changed": (
        "新文件里没有原来的主程序，它可能是补丁或语言包，不能替换整个游戏。旧版本没有动。"
    ),
    "disk_full": "磁盘空间不足，已停止。旧版本和存档都没有动。",
    "swap_failed": "替换文件夹失败，可能有文件正在使用。旧版本已恢复原位。",
    "saves_failed": "存档迁入新版本时校验失败，已恢复旧版本。备份还在。",
    "interrupted": "更新被中断了。已检查并恢复到安全状态，旧版本和存档都在。",
    "cancelled": "已取消更新，旧版本和存档都没有动。",
    "unexpected": "更新时发生意外错误，已恢复到旧版本。",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while block := stream.read(_HASH_BYTES):
            digest.update(block)
    return digest.hexdigest()


def _files_under(path: Path) -> list[Path]:
    """Files below a file or folder. Links are not followed out of the place named."""
    if path.is_file():
        return [path]
    found: list[Path] = []
    stack = [str(path)]
    while stack:
        with os.scandir(stack.pop()) as entries:
            for entry in entries:
                if entry.is_symlink() or entry.is_junction():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
                else:
                    found.append(Path(entry.path))
    return found


@dataclass(frozen=True)
class SavedFile:
    rule: int
    relative: str
    stored: str
    path: Path
    size: int
    is_file_rule: bool


class _Stop(Exception):
    def __init__(self, state: str, code: str | None) -> None:
        super().__init__(state)
        self.state = state
        self.code = code


@dataclass
class _Control:
    event: threading.Event


class GameUpdater:
    def __init__(
        self,
        engine: Engine,
        settings: Settings,
        downloads: DownloadQueue | None,
        extractions: ExtractionService,
    ) -> None:
        self._engine = engine
        self._backups = settings.data_dir / "save-backups"
        self._downloads = downloads
        self._extractions = extractions
        self._lock = threading.Lock()
        self._running: dict[str, _Control] = {}
        self._threads: dict[str, threading.Thread] = {}
        # Between checking the folders and moving them. Tests stop here to prove the undo.
        self.before_swap: Callable[[], None] = lambda: None

    # --- start and stop of the service ---

    def recover(self) -> None:
        """Looks at what is on disk. A swap caught halfway is undone; an update waiting for the
        user's word keeps waiting. Nothing starts by itself."""
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(game_updates).where(game_updates.c.state.in_(_WORKING))
            ).all()
        for row in rows:
            self._undo_swap(row)
            self._discard_staging(row)
            self._finish(row.id, "interrupted", "interrupted")

    def shutdown(self) -> None:
        with self._lock:
            threads = list(self._threads.values())
            for control in self._running.values():
                control.event.set()
        for thread in threads:
            thread.join(timeout=10)

    # --- saves ---

    def _config(self, connection: Connection, work_id: str) -> Row[Any] | None:
        return connection.execute(
            select(save_configs).where(save_configs.c.work_id == work_id)
        ).first()

    def save_config(self, work_id: str) -> models.SaveConfigOut:
        with self._engine.connect() as connection:
            get_ordinary_work(connection, work_id)
            row = self._config(connection, work_id)
        return models.SaveConfigOut(
            rules=[models.SaveRule(**rule) for rule in json.loads(row.rules)] if row else [],
            confirmed_none=bool(row.confirmed_none) if row else False,
        )

    def set_save_config(self, work_id: str, body: models.SaveConfigIn) -> models.SaveConfigOut:
        for rule in body.rules:
            if rule.kind == "inside":
                try:
                    safe_parts(rule.path)
                except ArchiveProblem:
                    raise AtlasError(
                        "save_rule_invalid", "存档路径必须在游戏文件夹内。", status=422
                    ) from None
            else:
                path = Path(rule.path)
                if not path.is_absolute() or is_protected(path):
                    raise AtlasError(
                        "save_rule_invalid", "请提供完整路径，不能是系统文件夹。", status=422
                    )
        if body.confirmed_none and body.rules:
            raise AtlasError("save_rule_invalid", "不能同时填写存档位置和“没有存档”。", status=422)
        rules = json.dumps([rule.model_dump() for rule in body.rules], ensure_ascii=False)
        with writing(self._engine).begin() as connection:
            get_ordinary_work(connection, work_id)
            connection.execute(delete(save_configs).where(save_configs.c.work_id == work_id))
            connection.execute(
                save_configs.insert().values(
                    work_id=work_id,
                    rules=rules,
                    confirmed_none=1 if body.confirmed_none else 0,
                    updated_at=_now(),
                )
            )
        return self.save_config(work_id)

    @staticmethod
    def _targets(rule: dict[str, str], root: Path) -> Path:
        if rule["kind"] == "inside":
            return root.joinpath(*safe_parts(rule["path"]))
        return Path(rule["path"])

    def save_target(self, rule: dict[str, str], root: Path) -> Path:
        return self._targets(rule, root)

    def saved_files(self, root: Path, rules: list[dict[str, str]]) -> list[SavedFile]:
        """What the rules name right now. A rule that finds nothing adds nothing."""
        found = []
        for index, rule in enumerate(rules):
            source = self._targets(rule, root)
            if not source.exists():
                continue
            for file in _files_under(source):
                relative = file.relative_to(source).as_posix() if source.is_dir() else file.name
                found.append(
                    SavedFile(
                        index,
                        relative,
                        f"{index}/{relative}",
                        file,
                        file.stat().st_size,
                        source.is_file(),
                    )
                )
        return found

    def protect_saves(self, work_id: str, root: Path, rules: list[dict[str, str]]) -> str:
        """A checked local backup, for anyone about to touch these saves."""
        try:
            return self.backup(work_id, root, rules)
        except _Stop:
            raise AtlasError(
                "backup_failed", "本地存档备份失败，已停止，存档没有改动。", status=409
            ) from None

    def is_running(self, program: Path) -> bool:
        try:
            self._refuse_if_running(program)
        except AtlasError:
            return True
        return False

    def refuse_if_running(self, root: Path, entry: str) -> None:
        self._refuse_if_running(root / entry)

    def backup(self, work_id: str, root: Path, rules: list[dict[str, str]]) -> str:
        """Copies, then proves it: every file re-read and compared, then restored into a separate
        place and compared again. A rule that finds nothing is recorded as such, because a game
        with no save yet is normal, but an unconfirmed one never gets this far."""
        backup_id = uuid.uuid4().hex
        folder = self._backups / work_id / backup_id
        manifest: list[dict[str, Any]] = []
        try:
            for index, rule in enumerate(rules):
                source = self._targets(rule, root)
                if not source.exists():
                    continue
                for file in _files_under(source):
                    relative = file.relative_to(source).as_posix() if source.is_dir() else file.name
                    stored = f"{index}/{relative}"
                    target = folder.joinpath(*stored.split("/"))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file, target)
                    digest = _hash(file)
                    if _hash(target) != digest:
                        raise _Stop("failed", "backup_failed")
                    manifest.append(
                        {
                            "rule": index,
                            "relative": relative,
                            "stored": stored,
                            "size": file.stat().st_size,
                            "sha256": digest,
                            "is_file_rule": source.is_file(),
                        }
                    )
            self._prove_restorable(folder, manifest)
        except OSError:
            shutil.rmtree(folder, ignore_errors=True)
            raise _Stop("failed", "backup_failed") from None
        except _Stop:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        folder.mkdir(parents=True, exist_ok=True)
        with writing(self._engine).begin() as connection:
            connection.execute(
                save_backups.insert().values(
                    id=backup_id,
                    work_id=work_id,
                    path=str(folder),
                    rules=json.dumps(rules, ensure_ascii=False),
                    manifest=json.dumps(manifest, ensure_ascii=False),
                    created_at=_now(),
                )
            )
        self._prune(work_id)
        return backup_id

    def _prove_restorable(self, folder: Path, manifest: list[dict[str, Any]]) -> None:
        self._backups.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self._backups) as trial:
            for item in manifest:
                source = folder.joinpath(*item["stored"].split("/"))
                target = Path(trial).joinpath(*item["stored"].split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                if target.stat().st_size != item["size"] or _hash(target) != item["sha256"]:
                    raise _Stop("failed", "backup_failed")

    def _prune(self, work_id: str) -> None:
        """Keeps the newest few. Backups outlive old game folders: that is what they are for."""
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(save_backups)
                .where(save_backups.c.work_id == work_id)
                .order_by(save_backups.c.created_at.desc())
            ).all()
        for row in rows[_KEEP_BACKUPS:]:
            shutil.rmtree(row.path, ignore_errors=True)
            with writing(self._engine).begin() as connection:
                connection.execute(delete(save_backups).where(save_backups.c.id == row.id))

    def backups(self, work_id: str) -> list[models.SaveBackupOut]:
        with self._engine.connect() as connection:
            get_ordinary_work(connection, work_id)
            rows = connection.execute(
                select(save_backups)
                .where(save_backups.c.work_id == work_id)
                .order_by(save_backups.c.created_at.desc())
            ).all()
        return [
            models.SaveBackupOut(
                id=row.id,
                created_at=row.created_at,
                files=len(json.loads(row.manifest)),
                available=Path(row.path).is_dir(),
            )
            for row in rows
        ]

    def restore(self, backup_id: str, copy_id: str) -> models.SaveRestoreOut:
        """Puts a backup back, after backing up what is there now: a newer save is never lost to
        an older one. Only the places the rules name are written, and each file is checked."""
        with self._engine.connect() as connection:
            row = connection.execute(
                select(save_backups).where(save_backups.c.id == backup_id)
            ).first()
            if row is None:
                raise AtlasError("backup_not_found", "找不到这份备份。", status=404)
            get_ordinary_work(connection, row.work_id)
            copy = self._copy(connection, copy_id)
        if copy.work_id != row.work_id:
            raise AtlasError("backup_not_found", "这份备份不属于这个副本。", status=404)
        root = Path(copy.root_path)
        if not root.is_dir():
            raise AtlasError("copy_unavailable", MESSAGES["copy_unavailable"], status=409)
        rules = json.loads(row.rules)
        before = self.backup(row.work_id, root, rules)
        written = 0
        try:
            for item in json.loads(row.manifest):
                rule = rules[item["rule"]]
                base = self._targets(rule, root)
                target = (
                    base
                    if item.get("is_file_rule")
                    else base.joinpath(*item["relative"].split("/"))
                )
                if rule["kind"] == "inside" and not target.resolve().is_relative_to(root.resolve()):
                    raise AtlasError("save_rule_invalid", "存档路径越界，已停止。", status=409)
                source = Path(row.path).joinpath(*item["stored"].split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                partial = target.with_name(f".{target.name}.atlas-restore")
                shutil.copy2(source, partial)
                if _hash(partial) != item["sha256"]:
                    partial.unlink(missing_ok=True)
                    raise AtlasError("restore_failed", "备份文件已损坏，已停止。", status=409)
                os.replace(partial, target)
                written += 1
        except OSError:
            raise AtlasError(
                "restore_failed", "恢复没有完成。恢复前的存档已备份。", status=409
            ) from None
        return models.SaveRestoreOut(restored=written, safety_backup_id=before)

    # --- reading ---

    def _out(self, row: Row[Any]) -> models.GameUpdateOut:
        return models.GameUpdateOut(
            id=row.id,
            copy_id=row.copy_id,
            state=cast(models.UpdateState, row.state),
            code=row.error_code,
            message=MESSAGES.get(row.error_code) if row.error_code else None,
            extra_count=row.extra_count,
            extra_sample=json.loads(row.extra_sample or "[]"),
            cleanup_failed=bool(row.cleanup_failed),
            can_retry=row.state in ("failed", "cancelled", "interrupted", "rolled_back"),
            created_at=row.created_at,
            finished_at=row.finished_at,
        )

    def status(self, work_id: str) -> models.GameUpdateStatus:
        with self._engine.connect() as connection:
            get_ordinary_work(connection, work_id)
            row = connection.execute(
                select(game_updates)
                .where(game_updates.c.work_id == work_id)
                .order_by(game_updates.c.created_at.desc())
                .limit(1)
            ).first()
        return models.GameUpdateStatus(
            task=self._out(row) if row else None,
            config=self.save_config(work_id),
            backups=self.backups(work_id),
        )

    @staticmethod
    def _copy(connection: Connection, copy_id: str) -> Row[Any]:
        row = connection.execute(select(local_copies).where(local_copies.c.id == copy_id)).first()
        if row is None:
            raise AtlasError("copy_not_found", "找不到这个本地文件关联。", status=404)
        get_ordinary_work(connection, row.work_id)
        return row

    def _task(self, connection: Connection, task_id: str) -> Row[Any]:
        row = connection.execute(select(game_updates).where(game_updates.c.id == task_id)).first()
        if row is None:
            raise AtlasError("update_not_found", "找不到这个更新任务。", status=404)
        get_ordinary_work(connection, row.work_id)
        return row

    # --- starting ---

    def start(self, work_id: str, body: models.GameUpdateStart) -> models.GameUpdateStatus:
        """Refuses before anything happens: a missing answer is never read as a yes."""
        with self._engine.connect() as connection:
            get_ordinary_work(connection, work_id)
            copy = self._copy(connection, body.copy_id)
            config = self._config(connection, work_id)
        if copy.work_id != work_id:
            raise AtlasError("copy_not_found", "找不到这个本地文件关联。", status=404)
        if config is None or (not json.loads(config.rules) and not config.confirmed_none):
            raise AtlasError("saves_unconfirmed", MESSAGES["saves_unconfirmed"], status=409)
        if not body.confirm_closed:
            raise AtlasError("confirm_closed", MESSAGES["confirm_closed"], status=409)
        root = Path(copy.root_path)
        if not root.is_dir():
            raise AtlasError("copy_unavailable", MESSAGES["copy_unavailable"], status=409)
        if not copy.entry_path or not (root / copy.entry_path).is_file():
            raise AtlasError("no_entry", MESSAGES["no_entry"], status=409)
        self._refuse_if_running(root / copy.entry_path)
        task_id = uuid.uuid4().hex
        try:
            with writing(self._engine).begin() as connection:
                connection.execute(
                    game_updates.insert().values(
                        id=task_id,
                        work_id=work_id,
                        copy_id=copy.id,
                        state="queued",
                        active_key=copy.id,
                        root_path=str(root),
                        created_at=_now(),
                        updated_at=_now(),
                    )
                )
        except IntegrityError:
            raise AtlasError("update_exists", "这个副本已经在更新了。", status=409) from None
        self._launch(task_id)
        return self.status(work_id)

    @staticmethod
    def _refuse_if_running(program: Path) -> None:
        """Windows will not let a running program be opened for writing. That much is evidence;
        its absence proves little, which is why the user is also asked."""
        try:
            with open(program, "r+b"):
                pass
        except PermissionError:
            raise AtlasError("game_running", MESSAGES["game_running"], status=409) from None
        except OSError:
            return

    def _launch(self, task_id: str) -> None:
        control = _Control(threading.Event())
        with self._lock:
            self._running[task_id] = control
            thread = threading.Thread(
                target=self._run, args=(task_id, control), name="game-update", daemon=True
            )
            self._threads[task_id] = thread
            thread.start()

    def retry(self, task_id: str) -> models.GameUpdateStatus:
        """Reuses a download that already finished: only the unfinished steps run again."""
        with writing(self._engine).begin() as connection:
            row = self._task(connection, task_id)
            if row.state not in ("failed", "cancelled", "interrupted", "rolled_back"):
                return self.status(row.work_id)
            try:
                with connection.begin_nested():
                    connection.execute(
                        update(game_updates)
                        .where(game_updates.c.id == task_id)
                        .values(
                            state="queued",
                            active_key=row.copy_id,
                            error_code=None,
                            finished_at=None,
                            updated_at=_now(),
                        )
                    )
            except IntegrityError:
                raise AtlasError("update_exists", "这个副本已经在更新了。", status=409) from None
        self._launch(task_id)
        return self.status(row.work_id)

    def cancel(self, task_id: str) -> models.GameUpdateStatus:
        """Only before the swap. After that, the choices are the new version or the old one."""
        with self._engine.connect() as connection:
            row = self._task(connection, task_id)
        with self._lock:
            control = self._running.get(task_id)
            if control is not None and row.state in (
                "queued",
                "backing_up",
                "downloading",
                "unpacking",
            ):
                control.event.set()
        return self.status(row.work_id)

    # --- the task ---

    def _set(self, task_id: str, **values: Any) -> None:
        with writing(self._engine).begin() as connection:
            connection.execute(
                update(game_updates)
                .where(game_updates.c.id == task_id)
                .values(updated_at=_now(), **values)
            )

    def _finish(self, task_id: str, state: str, code: str | None) -> None:
        values: dict[str, Any] = {"state": state, "error_code": code, "finished_at": _now()}
        if state not in _HOLDS_KEY:
            values["active_key"] = None
        self._set(task_id, **values)

    def _run(self, task_id: str, control: _Control) -> None:
        with self._engine.connect() as connection:
            row = connection.execute(select(game_updates).where(game_updates.c.id == task_id)).one()
        try:
            self._execute(row, control)
        except _Stop as stop:
            self._undo_swap(self._fresh(task_id))
            self._discard_staging(self._fresh(task_id))
            self._finish(task_id, stop.state, stop.code)
        except Exception as error:  # noqa: BLE001 - must end the task; type only, no paths.
            logger.error("game update failed: %s", type(error).__name__)
            self._undo_swap(self._fresh(task_id))
            self._discard_staging(self._fresh(task_id))
            self._finish(task_id, "failed", "unexpected")
        finally:
            with self._lock:
                self._running.pop(task_id, None)
                self._threads.pop(task_id, None)

    def _fresh(self, task_id: str) -> Row[Any]:
        with self._engine.connect() as connection:
            return connection.execute(
                select(game_updates).where(game_updates.c.id == task_id)
            ).one()

    @staticmethod
    def _check(control: _Control) -> None:
        if control.event.is_set():
            raise _Stop("cancelled", "cancelled")

    def _execute(self, row: Row[Any], control: _Control) -> None:
        root = Path(row.root_path)
        with self._engine.connect() as connection:
            copy = self._copy(connection, row.copy_id)
            config = self._config(connection, row.work_id)
        rules = json.loads(config.rules) if config else []
        # 1. Saves first. Nothing later happens without a proven backup.
        self._set(row.id, state="backing_up")
        if not root.is_dir():
            raise _Stop("failed", "copy_unavailable")
        backup_id = self.backup(row.work_id, root, rules)
        self._set(row.id, backup_id=backup_id)
        self._check(control)
        # 2. The new files, through the ordinary queue. A retry reuses a finished download.
        self._set(row.id, state="downloading")
        inputs = self._download(row, control)
        self._check(control)
        # 3. Beside the old folder, on the same drive, so the swap is only a rename.
        self._set(row.id, state="unpacking")
        staging = root.parent / f".atlas-update-{row.id}"
        self._set(row.id, staging_path=str(staging))
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir()

        def check() -> None:
            if control.event.is_set():
                raise Stopped

        try:
            self._extractions.unpack_into(inputs, staging, check)
        except ArchiveProblem as problem:
            code = problem.code if problem.code in MESSAGES else "entry_changed"
            raise _Stop("failed", code) from None
        except Stopped:
            raise _Stop("cancelled", "cancelled") from None
        except OSError:
            raise _Stop("failed", "disk_full") from None
        # A patch or language pack would not hold the game's own program.
        if not (staging / copy.entry_path).is_file():
            raise _Stop("failed", "entry_changed")
        self._check(control)
        # 4. The swap. From here the choices are the new version or the old one, not cancelling.
        old = root.parent / f"{root.name}.atlas-old-{row.id}"
        self._set(row.id, state="replacing", old_path=str(old))
        self.before_swap()
        try:
            os.rename(root, old)
        except OSError:
            self._set(row.id, old_path=None)
            raise _Stop("failed", "swap_failed") from None
        try:
            os.rename(staging, root)
        except OSError:
            raise _Stop("failed", "swap_failed") from None
        # 5. Saves across, checked. The rest of the old folder stays out: that is the point.
        self._carry_saves(row.work_id, backup_id, rules, old, root)
        # 6. Waiting for the user: only playing it can show the new version takes these saves.
        count, sample = self._extras(old, root, rules)
        self._set(
            row.id,
            state="awaiting_confirmation",
            extra_count=count,
            extra_sample=json.dumps(sample, ensure_ascii=False),
            finished_at=_now(),
        )
        self._extractions.remove_task_files(json.loads(self._fresh(row.id).source_task_ids or "[]"))

    def _download(self, row: Row[Any], control: _Control) -> list[Path]:
        if self._downloads is None:
            raise _Stop("failed", "download_failed")
        known = json.loads(row.source_task_ids or "[]")
        if known and self._downloads.files_ready(known):
            return self._downloads.files_of(known)
        try:
            ids = self._downloads.fetch_again(row.work_id)
        except AtlasError:
            raise _Stop("failed", "download_failed") from None
        self._set(row.id, source_task_ids=json.dumps(ids))
        while True:
            states = self._downloads.states_of(ids)
            if all(state == "done" for state in states):
                return self._downloads.files_of(ids)
            if any(
                state in ("failed", "cancelled", "reauth_required", "interrupted")
                for state in states
            ):
                raise _Stop("failed", "download_failed")
            if control.event.wait(_POLL):
                for task_id in ids:
                    self._downloads.cancel(task_id)
                raise _Stop("cancelled", "cancelled")

    def _carry_saves(
        self, work_id: str, backup_id: str, rules: list[dict[str, str]], old: Path, root: Path
    ) -> None:
        """Only saves inside the game's folder move. Those outside it were never touched. The
        user's save replaces anything of that name in the new version: it is theirs."""
        with self._engine.connect() as connection:
            manifest = json.loads(
                connection.execute(
                    select(save_backups.c.manifest).where(save_backups.c.id == backup_id)
                ).scalar_one()
            )
        try:
            for item in manifest:
                rule = rules[item["rule"]]
                if rule["kind"] != "inside":
                    continue
                base = root.joinpath(*safe_parts(rule["path"]))
                source_base = old.joinpath(*safe_parts(rule["path"]))
                if item.get("is_file_rule"):
                    source, target = source_base, base
                else:
                    parts = item["relative"].split("/")
                    source, target = source_base.joinpath(*parts), base.joinpath(*parts)
                if not target.resolve().is_relative_to(root.resolve()):
                    raise _Stop("failed", "saves_failed")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                if _hash(target) != item["sha256"]:
                    raise _Stop("failed", "saves_failed")
        except OSError:
            raise _Stop("failed", "saves_failed") from None

    @staticmethod
    def _extras(old: Path, root: Path, rules: list[dict[str, str]]) -> tuple[int, list[str]]:
        """What only the old folder has, for the user to see before it goes: most is outdated
        program files, but it could be something of theirs that no rule named."""
        keep = [
            "/".join(safe_parts(rule["path"])).casefold()
            for rule in rules
            if rule["kind"] == "inside"
        ]
        count = 0
        sample: list[str] = []
        walked = 0
        for file in _files_under(old):
            walked += 1
            if walked > _MAX_WALK:
                break
            relative = file.relative_to(old).as_posix()
            folded = relative.casefold()
            if any(folded == item or folded.startswith(f"{item}/") for item in keep):
                continue
            if not (root / relative).exists():
                count += 1
                if len(sample) < _MAX_EXTRA_SAMPLE:
                    sample.append(relative)
        return count, sample

    # --- after the swap ---

    def confirm(self, task_id: str) -> models.GameUpdateStatus:
        """The user says the new version is good. Only now does the old folder go, and only the
        one this task made, recognized by the name it was given."""
        with self._engine.connect() as connection:
            row = self._task(connection, task_id)
        if row.state != "awaiting_confirmation":
            return self.status(row.work_id)
        old = Path(row.old_path)
        expected = f"{Path(row.root_path).name}.atlas-old-{row.id}"
        if old.name != expected or old.parent != Path(row.root_path).parent:
            raise AtlasError("update_invalid", "旧版本的位置和记录不符，没有删除。", status=409)
        self._set(row.id, state="cleaning")
        failed = False
        try:
            shutil.rmtree(old)
        except OSError:
            failed = True
            logger.warning("could not remove the old version of a game")
        self._set(row.id, cleanup_failed=1 if failed else 0)
        self._finish(row.id, "done", None)
        return self.status(row.work_id)

    def rollback(self, task_id: str) -> models.GameUpdateStatus:
        """Back to the old version. Whatever was saved in the new one is backed up first."""
        with self._engine.connect() as connection:
            row = self._task(connection, task_id)
            config = self._config(connection, row.work_id)
        if row.state != "awaiting_confirmation":
            return self.status(row.work_id)
        rules = json.loads(config.rules) if config else []
        try:
            self.backup(row.work_id, Path(row.root_path), rules)
        except _Stop:
            raise AtlasError("backup_failed", MESSAGES["backup_failed"], status=409) from None
        self._undo_swap(row)
        self._finish(row.id, "rolled_back", None)
        return self.status(row.work_id)

    def _undo_swap(self, row: Row[Any]) -> None:
        """Puts the old folder back if it is aside. The new one goes where it came from, and is
        only ever discarded under the staging name this task owns."""
        if not row.old_path:
            return
        old, root = Path(row.old_path), Path(row.root_path)
        if not old.is_dir():
            return
        staging = root.parent / f".atlas-update-{row.id}"
        if root.is_dir():
            os.rename(root, staging)
        os.rename(old, root)
        self._set(row.id, old_path=None, staging_path=str(staging))
        shutil.rmtree(staging, ignore_errors=True)

    @staticmethod
    def _discard_staging(row: Row[Any]) -> None:
        if row.staging_path and Path(row.staging_path).name == f".atlas-update-{row.id}":
            shutil.rmtree(row.staging_path, ignore_errors=True)
