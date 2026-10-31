"""The download queue: state lives here and in the database, never in the page.

A task's bytes go to `<archives>/.partial/<task id>.part`, which only this task owns, and move
to `<archives>/<work id>/<name>` only after the transfer is checked. An existing file is never
replaced: a taken name gets a number. A restart reports what it finds and sends nothing.

The database and the file system cannot commit together, so the intended name and hash are
written before the move. If the process dies in between, `recover` looks at the files to
decide: the part gone and a matching final file means the task did finish.

Every write names the attempt it belongs to, so a stopped worker cannot change a task that
has since been retried. Downloaded never means installed or playable.
"""

import errno
import hashlib
import logging
import os
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx
from sqlalchemy import Connection, Engine, Row, delete, select, update
from sqlalchemy.exc import IntegrityError

from app.adapters.dlsite.downloads import (
    Challenged,
    DownloadClient,
    DownloadPlan,
    FileGone,
    LoginRequired,
    NoPermission,
    NotAFile,
    OpenedFile,
    PlannedFile,
    RangeRejected,
    UnexpectedHost,
    Validators,
    looks_like_page,
)
from app.adapters.dlsite.library import PlatformUnavailable, ResponseChanged, SessionRejected
from app.adapters.dlsite.session import SessionCookie
from app.api import models
from app.core.errors import AtlasError
from app.db.engine import writing
from app.db.schema import download_tasks, personal_records, works
from app.domain.download_names import numbered, safe_file_name
from app.repositories import accounts
from app.repositories.works import ORDINARY, get_ordinary_work
from app.services.dlsite_auth import DlsiteAuth
from app.services.folders import FolderService

logger = logging.getLogger("atlas")

MAX_RUNNING = 2  # Enough that one huge file does not block the rest; gentle on the platform.
MAX_ATTEMPTS = 3
PROGRESS_INTERVAL = 0.5
_HASH_BYTES = 1024 * 1024
_LIST_LIMIT = 200
_PARTIAL = ".partial"  # Beside the finished archives, so finishing is only a rename.
_WORKING = ("queued", "resolving", "downloading", "verifying")
# One live task per file: held in `active_key`, which the database keeps unique.
_HOLDS_KEY = (*_WORKING, "paused")
_RESTARTABLE = ("failed", "interrupted", "reauth_required", "paused")
MESSAGES = {
    "session_expired": "DLsite 登录已失效，请重新登录后继续。",
    "session_changed": "账号状态变了，这个下载已停止，不会用新账号继续。",
    "account_changed": "这个任务属于之前的账号，不能用现在的账号继续。",
    "login_required": "DLsite 要求重新登录才能下载。如果重新登录后仍然这样，请反馈。",
    "challenged": "DLsite 要求人工验证，Atlas 不会绕过。请稍后重试。",
    "no_permission": "DLsite 拒绝了这个文件，可能没有下载权限或链接已过期。",
    "file_gone": "DLsite 上找不到这个文件。",
    "file_changed": "作品的文件组成变了，请重新发起下载。",
    "unexpected_host": "下载地址指向了 DLsite 以外的网站，已拦截，没有发送任何数据。",
    "not_a_file": "DLsite 返回的是网页或错误信息，不是文件，没有保存。",
    "empty_file": "DLsite 返回了空文件，没有保存。",
    "size_mismatch": "下载的大小和服务器声明的不一致，没有标记为完成。",
    "response_changed": "DLsite 返回的内容和预期不同，已停止。",
    "platform_unavailable": "暂时连不上 DLsite，可以重试。已下载的部分会尽量保留。",
    "folder_missing": "压缩包文件夹现在不存在，可能是硬盘没有连接。",
    "folder_invalid": "目标位置不在你选择的文件夹内，已停止。",
    "disk_full": "磁盘空间不足，下载已停止。",
    "write_failed": "无法写入文件，请检查文件夹权限。",
    "interrupted": "下载被中断了（服务关闭或异常退出）。",
    "cancelled": "已取消，未完成的部分已删除。",
    "unexpected": "下载时发生意外错误。",
}
_PLAN_ERRORS: dict[str, int] = {
    "session_expired": 409,
    "login_required": 409,
    "challenged": 409,
    "no_permission": 403,
    "file_gone": 404,
    "unexpected_host": 502,
    "response_changed": 502,
    "platform_unavailable": 503,
}
# These cannot be cured by trying again with the same answer from the platform.
_NOT_RETRYABLE = {"account_changed"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _platform_code(error: Exception) -> str | None:
    if isinstance(error, SessionRejected):
        return "session_expired"
    if isinstance(error, LoginRequired):
        return "login_required"
    if isinstance(error, Challenged):
        return "challenged"
    if isinstance(error, NoPermission):
        return "no_permission"
    if isinstance(error, FileGone):
        return "file_gone"
    if isinstance(error, UnexpectedHost):
        return "unexpected_host"
    if isinstance(error, NotAFile):
        return "not_a_file"
    if isinstance(error, ResponseChanged):
        return "response_changed"
    if isinstance(error, PlatformUnavailable):
        return "platform_unavailable"
    return None


def _write_code(error: OSError) -> str:
    full = error.errno == errno.ENOSPC or getattr(error, "winerror", None) in (39, 112)
    return "disk_full" if full else "write_failed"


class _Stop(Exception):
    def __init__(self, state: str, code: str | None, *, keep_part: bool = True) -> None:
        super().__init__(state)
        self.state = state
        self.code = code
        self.keep_part = keep_part


@dataclass
class _Control:
    """How a running worker is told to stop, and why."""

    event: threading.Event
    reason: str | None = None

    def stop(self, reason: str) -> None:
        # Cancelling outranks pausing; nothing overrides a cancel.
        if self.reason != "cancel":
            self.reason = reason
        self.event.set()


def _moment(text: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


class DownloadQueue:
    def __init__(
        self,
        engine: Engine,
        auth: DlsiteAuth,
        folders: FolderService,
        client_factory: Callable[[list[SessionCookie]], DownloadClient],
        *,
        wait_seconds: float = 2.0,
        free_space: Callable[[Path], int] = lambda path: shutil.disk_usage(path).free,
        on_shutdown: Callable[[], None] | None = None,
    ) -> None:
        self._engine = engine
        self._auth = auth
        self._folders = folders
        self._client_factory = client_factory
        self._wait_seconds = wait_seconds
        self._free_space = free_space
        self._on_shutdown = on_shutdown
        # Told when every file of a download the user asked to unpack has finished.
        self.on_flow_finished: Callable[[str], None] | None = None
        self._lock = threading.RLock()
        self._running: dict[str, _Control] = {}
        self._speeds: dict[str, int] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._closing = False

    # --- start and stop of the service ---

    def recover(self) -> None:
        """Reports what a restart finds. Nothing is requested and nothing restarts by itself."""
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(download_tasks).where(download_tasks.c.state.in_(_WORKING))
            ).all()
        for row in rows:
            self._remove_quietly(self._move_temp(row))
            if row.state == "verifying" and self._finished_before_crash(row):
                self._mark_done(row.id, row.attempt, row.work_id)
                self._remove_quietly(_part_path(row))
                continue
            self._write(row.id, row.attempt, state="interrupted", code="interrupted", ended=True)

    @staticmethod
    def _finished_before_crash(row: Row[Any]) -> bool:
        if not row.sha256 or not row.file_name:
            return False
        final = Path(row.target_dir) / row.file_name
        try:
            return bool(_hash_file(final, None) == row.sha256)
        except OSError:
            return False

    def shutdown(self) -> None:
        with self._lock:
            self._closing = True
            threads = list(self._threads.values())
            for control in self._running.values():
                control.stop("shutdown")
        for thread in threads:
            thread.join(timeout=5)
        if self._on_shutdown:
            self._on_shutdown()

    # --- reading ---

    def _ordinary_rows(self, connection: Connection, *conditions: Any) -> list[Row[Any]]:
        """Tasks of works ordinary views may show; a hidden work's task is as absent as it."""
        statement = (
            select(
                download_tasks,
                works.c.title,
                works.c.source_work_id,
                works.c.upgraded_at,
                works.c.download_size,
            )
            .join(works, works.c.id == download_tasks.c.work_id)
            .join(personal_records, personal_records.c.work_id == works.c.id)
            .where(ORDINARY, *conditions)
            .order_by(download_tasks.c.created_at.desc(), download_tasks.c.part_number)
            .limit(_LIST_LIMIT)
        )
        return list(connection.execute(statement).all())

    def _out(self, row: Row[Any]) -> models.DownloadTaskOut:
        done = row.state == "done"
        file_missing = False
        if done and not row.archive_removed:
            try:
                file_missing = (Path(row.target_dir) / row.file_name).stat().st_size != (
                    row.bytes_done
                )
            except OSError:
                file_missing = True
        return models.DownloadTaskOut(
            id=row.id,
            work_id=row.work_id,
            title=row.title,
            part=row.part_number or None,
            part_count=row.part_count,
            state=cast(models.DownloadState, row.state),
            bytes_done=row.bytes_done,
            bytes_total=row.bytes_total,
            file_name=row.file_name,
            code=row.error_code,
            message=MESSAGES.get(row.error_code) if row.error_code else None,
            can_retry=row.state in (*_RESTARTABLE, "cancelled")
            and row.error_code not in _NOT_RETRYABLE,
            can_resume=bool(
                row.state in _RESTARTABLE and row.bytes_done and row.bytes_total and _resumable(row)
            ),
            integrity=row.integrity,
            location=row.target_dir if done else None,
            file_missing=file_missing,
            archive_removed=bool(row.archive_removed),
            dismissed=bool(row.dismissed),
            bytes_per_second=self._speeds.get(row.id) if row.state == "downloading" else None,
            created_at=row.created_at,
            finished_at=row.finished_at,
        )

    def tasks(self, work_id: str | None = None) -> models.DownloadsOut:
        conditions = [download_tasks.c.work_id == work_id] if work_id else []
        with self._engine.connect() as connection:
            rows = self._ordinary_rows(connection, *conditions)
        out = [self._out(row) for row in rows]
        self._refresh_missing(out)
        return models.DownloadsOut(
            tasks=out,
            active_count=sum(1 for task in out if task.state in _HOLDS_KEY),
            updates=self._updates(rows, out),
        )

    @staticmethod
    def _has_newer_version(row: Row[Any]) -> bool:
        """With the platform's date from download time, any change counts: what the dates mean is
        the platform's business. Without one, a date only counts if it is later than the download,
        or filling in a date the platform always had would read as a new version."""
        if not row.upgraded_at:
            return False
        if row.source_upgraded_at:
            return bool(row.upgraded_at != row.source_upgraded_at)
        platform, downloaded = _moment(row.upgraded_at), _moment(row.created_at)
        return platform is not None and downloaded is not None and platform > downloaded

    @staticmethod
    def _updates(
        rows: list[Row[Any]], out: list[models.DownloadTaskOut]
    ) -> list[models.DownloadUpdate]:
        """Works whose newest download is older than what the platform now has."""
        missing = {task.id for task in out if task.file_missing}
        busy = {row.work_id for row in rows if row.state in _HOLDS_KEY}
        seen: set[str] = set()
        updates = []
        for row in rows:  # Newest first.
            if row.state != "done" or row.work_id in seen:
                continue
            seen.add(row.work_id)
            if (
                row.work_id not in busy
                and row.id not in missing
                and DownloadQueue._has_newer_version(row)
            ):
                updates.append(
                    models.DownloadUpdate(
                        work_id=row.work_id, title=row.title, size_bytes=row.download_size
                    )
                )
        return updates

    def _refresh_missing(self, tasks: list[models.DownloadTaskOut]) -> None:
        """A file the user moved or deleted means the work is no longer known to be here."""
        gone = {task.work_id for task in tasks if task.file_missing}
        kept = {task.work_id for task in tasks if task.state == "done" and not task.file_missing}
        for work_id in gone - kept:
            with writing(self._engine).begin() as connection:
                connection.execute(
                    update(works)
                    .where(works.c.id == work_id, works.c.local_state == "available")
                    .values(local_state="unknown")
                )

    def _task(self, connection: Connection, task_id: str) -> Row[Any]:
        rows = self._ordinary_rows(connection, download_tasks.c.id == task_id)
        if not rows:
            raise AtlasError("task_not_found", "找不到这个下载任务。", status=404)
        return rows[0]

    def _one(self, task_id: str) -> models.DownloadTaskOut:
        with self._engine.connect() as connection:
            return self._out(self._task(connection, task_id))

    # --- planning ---

    def _downloadable_work(self, connection: Connection, work_id: str) -> Row[Any]:
        """The server's own check: a hidden button proves nothing about a request."""
        row = get_ordinary_work(connection, work_id)
        if row.source_id != "dlsite":
            raise AtlasError("download_unsupported", "这部作品不能由 Atlas 下载。", status=409)
        if row.official_viewer_only or row.can_download == 0:
            raise AtlasError("download_unsupported", "这部作品平台不提供下载。", status=409)
        return row

    def _resolve_plan(self, source_work_id: str) -> DownloadPlan:
        cookies, generation = self._auth.session_for_sync()
        client = self._client_factory(cookies)
        try:
            return client.plan(source_work_id)
        except Exception as error:
            code = _platform_code(error)
            if code is None:
                raise
            if code == "session_expired":
                self._auth.session_rejected(generation)
            raise AtlasError(
                code,
                MESSAGES[code],
                status=_PLAN_ERRORS.get(code, 502),
                retryable=code == "platform_unavailable",
            ) from None
        finally:
            client.close()

    def plan(self, work_id: str) -> models.DownloadPlanOut:
        with self._engine.connect() as connection:
            row = self._downloadable_work(connection, work_id)
        plan = self._resolve_plan(row.source_work_id)
        return models.DownloadPlanOut(
            kind=plan.kind,
            parts=[file.number for file in plan.files if file.number is not None],
            total_bytes=row.download_size,
            folder=self._folders.describe_library(),
            free_bytes=self._free_bytes(),
        )

    def _free_bytes(self) -> int | None:
        try:
            library, _cache = self._folders.download_targets()
            return self._free_space(library)
        except (AtlasError, OSError):
            return None

    # --- control ---

    def create(self, body: models.DownloadCreate) -> models.DownloadsOut:
        with self._engine.connect() as connection:
            work = self._downloadable_work(connection, body.work_id)
            account = accounts.get_account(connection)
        _library, cache = self._folders.download_targets()
        plan = self._resolve_plan(work.source_work_id)
        if plan.kind == "serial":
            raise AtlasError(
                "download_serial", "这部作品需要序列号，暂不支持在 Atlas 内下载。", status=409
            )
        wanted = list(plan.files)
        if body.parts is not None:
            available = {file.number for file in plan.files}
            if not set(body.parts) <= available:
                raise AtlasError("file_changed", MESSAGES["file_changed"], status=409)
            wanted = [file for file in plan.files if file.number in set(body.parts)]
        if not wanted:
            raise AtlasError("nothing_selected", "没有选择要下载的文件。", status=422)
        fingerprint = account.account_fingerprint if account else None
        target = cache / safe_file_name(work.source_work_id, "work")
        ids = [
            self._create_one(
                work, file, len(plan.files), fingerprint, target, cache, again=body.again
            )
            for file in wanted
        ]
        flow_id = uuid.uuid4().hex if body.extract else None
        if flow_id:
            with writing(self._engine).begin() as connection:
                connection.execute(
                    update(download_tasks)
                    .where(download_tasks.c.id.in_(ids))
                    .values(flow_id=flow_id)
                )
        self._pump()
        self._flow_check(flow_id)
        return self.tasks(body.work_id) if ids else self.tasks()

    def fetch_again(self, work_id: str) -> list[str]:
        """Every file of a work, fresh, for an update to use once they are all done."""
        with self._engine.connect() as connection:
            work = self._downloadable_work(connection, work_id)
            account = accounts.get_account(connection)
        _library, cache = self._folders.download_targets()
        plan = self._resolve_plan(work.source_work_id)
        if plan.kind == "serial" or not plan.files:
            raise AtlasError("download_serial", "这部作品需要序列号，暂不支持。", status=409)
        fingerprint = account.account_fingerprint if account else None
        target = cache / safe_file_name(work.source_work_id, "work")
        ids = [
            self._create_one(work, file, len(plan.files), fingerprint, target, cache, again=True)
            for file in plan.files
        ]
        self._pump()
        return ids

    def states_of(self, ids: list[str]) -> list[str]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(download_tasks.c.id, download_tasks.c.state).where(
                    download_tasks.c.id.in_(ids)
                )
            ).all()
        found = {row.id: row.state for row in rows}
        return [found.get(task_id, "failed") for task_id in ids]

    def files_of(self, ids: list[str]) -> list[Path]:
        """The finished files, part order, for tasks this service itself wrote."""
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(download_tasks)
                .where(download_tasks.c.id.in_(ids))
                .order_by(download_tasks.c.part_number)
            ).all()
        return [Path(row.target_dir) / row.file_name for row in rows if row.file_name]

    def files_ready(self, ids: list[str]) -> bool:
        return all(state == "done" for state in self.states_of(ids)) and all(
            path.is_file() for path in self.files_of(ids)
        )

    def _flow_check(self, flow_id: str | None) -> None:
        if not flow_id or self.on_flow_finished is None:
            return
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(download_tasks.c.state, download_tasks.c.work_id).where(
                    download_tasks.c.flow_id == flow_id
                )
            ).all()
        if rows and all(row.state == "done" for row in rows):
            self.on_flow_finished(rows[0].work_id)

    def _create_one(
        self,
        work: Row[Any],
        file: PlannedFile,
        file_count: int,
        fingerprint: str | None,
        target: Path,
        cache: Path,
        *,
        again: bool,
    ) -> str:
        part = file.number or 0
        key = f"{work.id}:{part}"
        with self._lock, writing(self._engine).begin() as connection:
            latest = connection.execute(
                select(download_tasks)
                .where(download_tasks.c.work_id == work.id, download_tasks.c.part_number == part)
                .order_by(download_tasks.c.created_at.desc())
                .limit(1)
            ).first()
            if latest is not None:
                if latest.state in _HOLDS_KEY and latest.state != "paused":
                    return str(latest.id)  # The same request sent twice is the same task.
                if latest.state == "done" and not again and self._still_there(latest):
                    return str(latest.id)
                same_account = latest.account_fingerprint == fingerprint
                if latest.state in _RESTARTABLE and same_account:
                    self._requeue(connection, latest, key)
                    return str(latest.id)
            task_id = uuid.uuid4().hex
            now = _now()
            try:
                connection.execute(
                    download_tasks.insert().values(
                        id=task_id,
                        work_id=work.id,
                        part_number=part,
                        part_count=file_count if part else None,
                        account_fingerprint=fingerprint,
                        source_upgraded_at=work.upgraded_at,
                        state="queued",
                        active_key=key,
                        target_dir=str(target),
                        cache_dir=str(cache / _PARTIAL),
                        created_at=now,
                        updated_at=now,
                    )
                )
            except IntegrityError:
                raise AtlasError(
                    "download_exists", "这个文件已经有一个下载任务了。", status=409
                ) from None
        return task_id

    @staticmethod
    def _still_there(row: Row[Any]) -> bool:
        if row.archive_removed:
            return True  # Removed on purpose once unpacked; the work itself is what counts.
        try:
            return bool((Path(row.target_dir) / row.file_name).stat().st_size == row.bytes_done)
        except OSError:
            return False

    @staticmethod
    def _requeue(connection: Connection, row: Row[Any], key: str) -> None:
        connection.execute(
            update(download_tasks)
            .where(download_tasks.c.id == row.id)
            .values(
                state="queued",
                active_key=key,
                attempt=row.attempt + 1,
                error_code=None,
                finished_at=None,
                updated_at=_now(),
            )
        )

    def retry(self, task_id: str) -> models.DownloadTaskOut:
        with self._lock, writing(self._engine).begin() as connection:
            row = self._task(connection, task_id)
            if row.error_code in _NOT_RETRYABLE:
                raise AtlasError("account_changed", MESSAGES["account_changed"], status=409)
            if row.state in _RESTARTABLE or row.state == "cancelled":
                key = f"{row.work_id}:{row.part_number}"
                try:
                    with connection.begin_nested():
                        self._requeue(connection, row, key)
                except IntegrityError:
                    raise AtlasError(
                        "download_exists", "这个文件已经有一个下载任务了。", status=409
                    ) from None
        self._pump()
        return self._one(task_id)

    def cancel(self, task_id: str) -> models.DownloadTaskOut:
        """Repeating it changes nothing. A task that has already finished stays finished."""
        with self._lock:
            with self._engine.connect() as connection:
                row = self._task(connection, task_id)
            control = self._running.get(task_id)
            if control is not None:
                control.stop("cancel")
            elif row.state in (*_RESTARTABLE, "queued"):
                self._write(row.id, row.attempt, state="cancelled", code="cancelled", ended=True)
                self._remove_quietly(_part_path(row))
        return self._one(task_id)

    def pause(self, task_id: str) -> models.DownloadTaskOut:
        with self._lock:
            with self._engine.connect() as connection:
                row = self._task(connection, task_id)
            control = self._running.get(task_id)
            if control is not None:
                control.stop("pause")
            elif row.state == "queued":
                self._write(row.id, row.attempt, state="paused")
        return self._one(task_id)

    def clear_finished(self) -> models.DownloadsOut:
        """Empties the finished list, as in Steam. Failed and cancelled records go with their
        leftovers. Finished ones stay on file, out of the list: they are how a newer version is
        noticed. No finished file or result is touched."""
        with self._engine.connect() as connection:
            rows = self._ordinary_rows(
                connection, download_tasks.c.state.in_(("cancelled", "failed", "done"))
            )
        with self._lock:
            for row in rows:
                if row.state != "done":
                    self._remove_quietly(_part_path(row))
            with writing(self._engine).begin() as connection:
                connection.execute(
                    delete(download_tasks).where(
                        download_tasks.c.id.in_([row.id for row in rows if row.state != "done"])
                    )
                )
                connection.execute(
                    update(download_tasks)
                    .where(download_tasks.c.id.in_([row.id for row in rows if row.state == "done"]))
                    .values(dismissed=1)
                )
        return self.tasks()

    def open_folder(self, task_id: str) -> models.DownloadTaskOut:
        """Only ever the folder a finished task wrote to; the request cannot name a path."""
        with self._engine.connect() as connection:
            row = self._task(connection, task_id)
        if row.state != "done":
            raise AtlasError("task_not_finished", "这个任务还没有完成。", status=409)
        self._folders.open_path(Path(row.target_dir))
        return self._out(row)

    # --- the queue ---

    def _pump(self) -> None:
        with self._lock:
            if self._closing:
                return
            room = MAX_RUNNING - len(self._running)
            if room <= 0:
                return
            with self._engine.connect() as connection:
                rows = connection.execute(
                    select(download_tasks)
                    # A worker only marks its task once it is running, so one just started still
                    # reads as queued: without this it would be started a second time.
                    .where(
                        download_tasks.c.state == "queued",
                        download_tasks.c.id.not_in(list(self._running)),
                    )
                    .order_by(download_tasks.c.created_at, download_tasks.c.part_number)
                    .limit(room)
                ).all()
            for row in rows:
                control = _Control(threading.Event())
                self._running[row.id] = control
                thread = threading.Thread(
                    target=self._run, args=(row, control), name="download", daemon=True
                )
                self._threads[row.id] = thread
                thread.start()

    def _write(
        self,
        task_id: str,
        attempt: int,
        *,
        code: str | None = None,
        ended: bool = False,
        **values: Any,
    ) -> bool:
        """False when this attempt no longer owns the task: its news is simply too late."""
        changes: dict[str, Any] = {"updated_at": _now(), **values}
        if "state" in values:
            changes["error_code"] = code
            if values["state"] not in _HOLDS_KEY:
                changes["active_key"] = None
        if ended:
            changes["finished_at"] = _now()
        with writing(self._engine).begin() as connection:
            result = connection.execute(
                update(download_tasks)
                .where(download_tasks.c.id == task_id, download_tasks.c.attempt == attempt)
                .values(**changes)
            )
        return bool(result.rowcount)

    def _run(self, row: Row[Any], control: _Control) -> None:
        client: DownloadClient | None = None
        try:
            with self._engine.connect() as connection:
                source_work_id = connection.execute(
                    select(works.c.source_work_id).where(works.c.id == row.work_id)
                ).scalar_one()
                account = accounts.get_account(connection)
            if (account.account_fingerprint if account else None) != row.account_fingerprint:
                raise _Stop("failed", "account_changed", keep_part=False)
            try:
                cookies, generation = self._auth.session_for_sync()
            except AtlasError:
                raise _Stop("reauth_required", "session_expired") from None
            client = self._client_factory(cookies)
            self._execute(row, control, client, source_work_id, generation)
        except _Stop as stop:
            self._write(
                row.id, row.attempt, state=stop.state, code=stop.code, ended=stop.state != "paused"
            )
            if not stop.keep_part:
                self._remove_quietly(_part_path(row))
        except Exception as error:  # noqa: BLE001 - must end the task; type only, no data.
            logger.error("download failed: %s", type(error).__name__)
            self._write(row.id, row.attempt, state="failed", code="unexpected", ended=True)
        finally:
            if client is not None:
                client.close()
            with self._lock:
                self._running.pop(row.id, None)
                self._threads.pop(row.id, None)
                self._speeds.pop(row.id, None)
            self._pump()

    def _check(self, control: _Control, generation: int) -> None:
        reason = control.reason
        if reason == "cancel":
            raise _Stop("cancelled", "cancelled", keep_part=False)
        if reason == "pause":
            raise _Stop("paused", None)
        if reason == "shutdown":
            raise _Stop("interrupted", "interrupted")
        if not self._auth.is_current(generation):
            raise _Stop("reauth_required", "session_changed")

    def _execute(
        self,
        row: Row[Any],
        control: _Control,
        client: DownloadClient,
        source_work_id: str,
        generation: int,
    ) -> None:
        cache = Path(row.cache_dir)
        if not cache.parent.is_dir():
            raise _Stop(
                "failed", "folder_missing"
            )  # Never recreated: it may be an unplugged drive.
        try:
            cache.mkdir(exist_ok=True)
        except OSError:
            raise _Stop("failed", "write_failed") from None
        state = _Transfer(row)
        refused = False
        for attempt in range(MAX_ATTEMPTS):
            self._check(control, generation)
            try:
                self._transfer(row, control, client, source_work_id, generation, state)
                break
            except NoPermission:
                # An address that has aged out: one fresh address, then believe the platform.
                if refused:
                    raise _Stop("failed", "no_permission") from None
                refused = True
            except PlatformUnavailable as error:
                if attempt == MAX_ATTEMPTS - 1:
                    raise _Stop("failed", "platform_unavailable") from None
                control.event.wait(error.retry_after or self._wait_seconds * (attempt + 1))
            except SessionRejected:
                self._auth.session_rejected(generation)
                raise _Stop("reauth_required", "session_expired") from None
            except LoginRequired:
                raise _Stop("reauth_required", "login_required") from None
            except (Challenged, FileGone, UnexpectedHost, NotAFile, ResponseChanged) as error:
                raise _Stop("failed", _platform_code(error), keep_part=False) from None
            except OSError as error:
                code = _write_code(error)
                raise _Stop("failed", code, keep_part=code != "disk_full") from None
        else:
            raise _Stop("failed", "no_permission")
        self._check(control, generation)
        self._commit(row, control, generation, state)

    def _transfer(
        self,
        row: Row[Any],
        control: _Control,
        client: DownloadClient,
        source_work_id: str,
        generation: int,
        state: _Transfer,
    ) -> None:
        self._write(row.id, row.attempt, state="resolving")
        plan = client.plan(source_work_id)
        planned = next((file for file in plan.files if (file.number or 0) == row.part_number), None)
        if planned is None:
            raise _Stop("failed", "file_changed", keep_part=False)
        self._check(control, generation)
        path = _part_path(row)
        offset = state.resume_offset(path)
        if state.total is not None and offset == state.total and offset > 0:
            return  # Everything arrived before the break; only checking is left.
        try:
            opened = client.open(planned.url, offset, state.validators)
        except RangeRejected:
            if not offset:
                raise ResponseChanged from None
            offset = 0
            state.forget()
            opened = client.open(planned.url, 0, Validators())
        try:
            if opened.partial and not state.same_resource(opened):
                # It changed under us. Appending would splice two different files.
                opened.close()
                state.forget()
                offset = 0
                opened = client.open(planned.url, 0, Validators())
            self._receive(row, control, generation, opened, path, state, source_work_id)
        finally:
            opened.close()

    def _receive(
        self,
        row: Row[Any],
        control: _Control,
        generation: int,
        opened: OpenedFile,
        path: Path,
        state: _Transfer,
        source_work_id: str,
    ) -> None:
        offset = opened.offset
        state.adopt(opened)
        fallback = f"{safe_file_name(source_work_id, 'work')}"
        fallback += f".part{row.part_number}.bin" if row.part_number else ".bin"
        state.name = safe_file_name(opened.name, fallback) if opened.name else fallback
        self._write(
            row.id,
            row.attempt,
            state="downloading",
            bytes_done=offset,
            bytes_total=state.total,
            etag=state.validators.etag,
            last_modified=state.validators.last_modified,
            file_name=state.name,
        )
        if state.total is not None:
            needed = state.total - offset
            for folder in {Path(row.cache_dir), Path(row.target_dir).parent}:
                try:
                    enough = self._free_space(folder) >= needed
                except OSError:
                    continue
                if not enough:
                    raise _Stop("failed", "disk_full", keep_part=False)
        done = offset
        last_report = time.monotonic()
        last_done = offset
        started = offset > 0
        with open(path, "r+b" if offset else "wb") as output:
            if offset:
                output.truncate(offset)
                output.seek(offset)
            try:
                for chunk in opened.chunks():
                    self._check(control, generation)
                    if not started:
                        if looks_like_page(chunk):
                            raise NotAFile
                        started = True
                    output.write(chunk)
                    done += len(chunk)
                    if state.total is not None and done > state.total:
                        raise _Stop("failed", "size_mismatch", keep_part=False)
                    now = time.monotonic()
                    if now - last_report >= PROGRESS_INTERVAL:
                        self._speeds[row.id] = int((done - last_done) / (now - last_report))
                        self._write(row.id, row.attempt, bytes_done=done)
                        last_report, last_done = now, done
            except httpx.HTTPError:
                output.flush()
                self._write(row.id, row.attempt, bytes_done=done)
                raise PlatformUnavailable from None
            except _Stop:
                # Stopped on purpose: the record has to say how far it really got.
                output.flush()
                self._write(row.id, row.attempt, bytes_done=done)
                raise
            output.flush()
            os.fsync(output.fileno())
        self._write(row.id, row.attempt, bytes_done=done)
        if not done:
            self._remove_quietly(path)
            raise _Stop("failed", "empty_file", keep_part=False)
        if state.total is not None and done < state.total:
            raise PlatformUnavailable  # Ended early without saying so: try the rest.

    def _commit(self, row: Row[Any], control: _Control, generation: int, state: _Transfer) -> None:
        self._write(row.id, row.attempt, state="verifying")
        part = _part_path(row)
        try:
            size = part.stat().st_size
            if state.total is not None and size != state.total:
                raise _Stop("failed", "size_mismatch", keep_part=False)
            digest = _hash_file(part, lambda: self._check(control, generation))
        except OSError:
            raise _Stop("failed", "write_failed") from None
        target = _checked_target(row)
        temp = self._move_temp(row)
        # On one drive the move below is atomic. Between drives, copy next to the target first.
        source = part
        if not _same_drive(part, target):
            try:
                shutil.copyfile(part, temp)
            except OSError as error:
                self._remove_quietly(temp)
                code = _write_code(error)
                raise _Stop("failed", code) from None
            source = temp
        self._check(control, generation)
        integrity = "length" if state.total is not None else "stream_end"
        # The commit point. A cancel that arrives first wins; after this the file is finished.
        with self._lock:
            self._check(control, generation)
            name = self._move_to_final(
                row, source, target, state.name or part.name, digest, integrity
            )
            self._mark_done(row.id, row.attempt, row.work_id, file_name=name)
        self._remove_quietly(part)
        with self._engine.connect() as connection:
            flow_id = connection.execute(
                select(download_tasks.c.flow_id).where(download_tasks.c.id == row.id)
            ).scalar()
        self._flow_check(flow_id)

    def _move_to_final(
        self, row: Row[Any], source: Path, target: Path, name: str, digest: str, integrity: str
    ) -> str:
        """Never replaces anything: `os.rename` refuses an existing name on Windows, and the
        check covers the rest. The intent is on record before the move, for `recover`."""
        for number in range(1, 1000):
            candidate = name if number == 1 else numbered(name, number)
            final = target / candidate
            if os.path.lexists(final):
                continue
            self._write(
                row.id, row.attempt, file_name=candidate, sha256=digest, integrity=integrity
            )
            try:
                os.rename(source, final)
                return candidate
            except FileExistsError:
                continue
            except OSError as error:
                raise _Stop("failed", _write_code(error)) from None
        raise _Stop("failed", "write_failed")

    def _mark_done(self, task_id: str, attempt: int, work_id: str, **values: Any) -> None:
        with writing(self._engine).begin() as connection:
            connection.execute(
                update(download_tasks)
                .where(download_tasks.c.id == task_id, download_tasks.c.attempt == attempt)
                .values(
                    state="done",
                    active_key=None,
                    error_code=None,
                    finished_at=_now(),
                    updated_at=_now(),
                    **values,
                )
            )
            # Downloaded, which is all this says. Sync leaves this column alone.
            connection.execute(
                update(works).where(works.c.id == work_id).values(local_state="available")
            )

    @staticmethod
    def _move_temp(row: Row[Any]) -> Path:
        return Path(row.target_dir) / f".{row.id}.atlas-tmp"

    @staticmethod
    def _remove_quietly(path: Path) -> None:
        """Only ever called with paths this task owns."""
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("could not remove a temporary download file")


class _Transfer:
    """What this task knows about the remote file, carried across tries."""

    def __init__(self, row: Row[Any]) -> None:
        self.validators = Validators(row.etag, row.last_modified)
        self.total: int | None = row.bytes_total
        self.name: str | None = row.file_name

    def forget(self) -> None:
        self.validators = Validators()
        self.total = None

    def resume_offset(self, path: Path) -> int:
        """Only with proof the remote file can be recognized, and a known end."""
        if not self.validators.strong or self.total is None:
            return 0
        try:
            return min(path.stat().st_size, self.total)
        except OSError:
            return 0

    def same_resource(self, opened: OpenedFile) -> bool:
        return opened.total == self.total and opened.validators.strong == self.validators.strong

    def adopt(self, opened: OpenedFile) -> None:
        self.total = opened.total
        self.validators = opened.validators


def _same_drive(first: Path, second: Path) -> bool:
    return first.stat().st_dev == second.stat().st_dev


def _resumable(row: Row[Any]) -> bool:
    return bool(Validators(row.etag, row.last_modified).strong) and _part_path(row).exists()


def _part_path(row: Row[Any]) -> Path:
    return Path(row.cache_dir) / f"{row.id}.part"


def _hash_file(path: Path, check: Callable[[], None] | None) -> str:
    """A local fingerprint for later comparison. The platform publishes none to check against."""
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while block := stream.read(_HASH_BYTES):
            if check:
                check()
            digest.update(block)
    return digest.hexdigest()


def _checked_target(row: Row[Any]) -> Path:
    """The folder must exist as chosen, and links must not lead the task out of it."""
    target = Path(row.target_dir)
    root = target.parent
    if not root.is_dir():
        raise _Stop("failed", "folder_missing")
    try:
        target.mkdir(exist_ok=True)
        resolved = target.resolve()
        if resolved.parent != root.resolve():
            raise _Stop("failed", "folder_invalid")
    except OSError:
        raise _Stop("failed", "write_failed") from None
    return resolved
