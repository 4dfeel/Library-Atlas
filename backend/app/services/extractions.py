"""Unpacks files the download queue finished. The only input is a work whose download tasks are
done: no request can name a path, and each file is checked against its recorded size and hash
before use, because a file on disk can change after it was downloaded.

Each attempt writes to its own `<folder>/.atlas-extract-<task id>`, and the result is compared
with the archive's listing. Only then is that folder renamed to `<type>/<maker>/<title>`, a name
checked to be free: existing folders are never merged into or replaced. Failing, cancelling or
restarting removes the attempt's folder and leaves the download alone, so a retry never
downloads again. Nothing inside an archive is run, and unpacked never means installed.
"""

import json
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

from sqlalchemy import Connection, Engine, Row, delete, select, update
from sqlalchemy.exc import IntegrityError

from app.adapters.system.archives import (
    CHUNK_BYTES,
    ArchiveProblem,
    Entry,
    Limits,
    Listing,
    Progress,
    SevenZip,
    Stopped,
    _measure,
    extract_zip,
    list_zip,
    sniff,
    verify_output,
)
from app.api import models
from app.core.errors import AtlasError
from app.db.engine import writing
from app.db.schema import download_tasks, extract_tasks, personal_records, works
from app.domain.download_names import safe_file_name, work_folder
from app.repositories import accounts
from app.repositories.works import ORDINARY, get_ordinary_work
from app.services.downloads import _hash_file
from app.services.folders import FolderService

logger = logging.getLogger("atlas")

MAX_RUNNING = 1  # Unpacking is heavy on the disk, and nothing is gained by doing two at once.
PROGRESS_INTERVAL = 0.5
_WORKING = ("queued", "checking", "extracting", "committing")
_LIST_LIMIT = 200
_STAGING_PREFIX = ".atlas-extract-"
MESSAGES = {
    "no_download": "这部作品还没有下载完成的文件。",
    "missing_parts": "分卷不齐全，请先下载所有分卷。",
    "input_changed": "已下载的文件变了或不在原位置，请重新下载后再解压。",
    "account_changed": "这个下载属于之前的账号，不能在现在的账号下解压。",
    "tool_missing": "解压这种格式需要 7-Zip（25.01 或更新版本）。请安装后重试。",
    "unsupported_format": "这种压缩格式暂不支持。下载的文件已保留。",
    "encrypted": "这个压缩包有密码，暂不支持。下载的文件已保留，可以用你自己的工具解压。",
    "name_encoding": "压缩包里的文件名编码无法确定，为避免乱码或覆盖，没有解压。",
    "unsafe_path": "压缩包里有不安全的路径（可能写到目标文件夹外），已拒绝，没有解压。",
    "duplicate_path": "压缩包里有在 Windows 上同名的文件，已拒绝，没有解压。",
    "special_entry": "压缩包里有链接等特殊条目，已拒绝。",
    "too_large": "解压内容超过了安全上限，已停止。",
    "damaged": "压缩包已损坏或不完整。可以重新下载后再试。",
    "extract_failed": "解压工具报告失败，原因未知。下载的文件已保留。",
    "output_mismatch": "解压结果和压缩包内容不一致，没有采用这次结果。",
    "disk_full": "磁盘空间不足，解压已停止。",
    "write_failed": "无法写入作品文件夹，请检查权限，或路径是否过长。",
    "folder_missing": "作品文件夹现在不存在，可能是硬盘没有连接。",
    "folder_invalid": "目标位置不在作品文件夹内，已停止。",
    "interrupted": "解压被中断了（服务关闭或异常退出），可以重新解压。",
    "cancelled": "已取消解压，下载的文件不受影响。",
    "unexpected": "解压时发生意外错误。下载的文件已保留。",
}
_START_ERRORS = {"no_download", "missing_parts", "account_changed"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


class _Stop(Exception):
    def __init__(self, state: str, code: str | None) -> None:
        super().__init__(state)
        self.state = state
        self.code = code


@dataclass
class _Control:
    event: threading.Event
    reason: str | None = None

    def stop(self, reason: str) -> None:
        if self.reason != "cancel":
            self.reason = reason
        self.event.set()


def _as_files(paths: list[Path]) -> Listing:
    return Listing("file", tuple(Entry(path.name, path.stat().st_size, False) for path in paths))


def _copy_files(
    sources: list[Path], folder: Path, progress: Progress, check: Callable[[], None]
) -> None:
    """A copy: the download stays where it is, and nothing is run."""
    done = 0
    for source in sources:
        with open(source, "rb") as reader, open(folder / source.name, "xb") as writer:
            while chunk := reader.read(CHUNK_BYTES):
                check()
                writer.write(chunk)
                done += len(chunk)
                progress(done)


def _staging(row: Row[Any]) -> Path:
    return Path(row.root_dir) / f"{_STAGING_PREFIX}{row.id}"


def _final(row: Row[Any]) -> Path | None:
    return Path(row.root_dir) / row.final_name if row.final_name else None


class ExtractionService:
    def __init__(
        self,
        engine: Engine,
        folders: FolderService,
        find_tool: Callable[[], SevenZip | None],
        *,
        limits: Limits | None = None,
        free_space: Callable[[Path], int] = lambda path: shutil.disk_usage(path).free,
    ) -> None:
        self._engine = engine
        self._folders = folders
        self._find_tool = find_tool
        self._limits = limits or Limits()
        self._free_space = free_space
        self._lock = threading.RLock()
        self._running: dict[str, _Control] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._closing = False

    # --- start and stop of the service ---

    def recover(self) -> None:
        """Looks at the files, then reports. A folder is only claimed when its name was chosen
        by this task and it holds exactly what the task recorded. Nothing restarts by itself."""
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(extract_tasks).where(extract_tasks.c.state.in_(_WORKING))
            ).all()
        for row in rows:
            staging, final = _staging(row), _final(row)
            finished = (
                row.state == "committing"
                and final is not None
                and final.is_dir()
                and not staging.exists()
                and _measure(final) == (row.bytes_total, row.files_total)
            )
            if finished:
                self._write(row.id, row.attempt, state="done", ended=True)
                continue
            self._remove_staging(row)
            self._write(row.id, row.attempt, state="interrupted", code="interrupted", ended=True)

    def shutdown(self) -> None:
        with self._lock:
            self._closing = True
            threads = list(self._threads.values())
            for control in self._running.values():
                control.stop("shutdown")
        for thread in threads:
            thread.join(timeout=10)

    # --- reading ---

    def _ordinary_rows(self, connection: Connection, *conditions: Any) -> list[Row[Any]]:
        statement = (
            select(extract_tasks, works.c.title)
            .join(works, works.c.id == extract_tasks.c.work_id)
            .join(personal_records, personal_records.c.work_id == works.c.id)
            .where(ORDINARY, *conditions)
            .order_by(extract_tasks.c.created_at.desc())
            .limit(_LIST_LIMIT)
        )
        return list(connection.execute(statement).all())

    def _out(self, row: Row[Any]) -> models.ExtractTaskOut:
        final = _final(row)
        done = row.state == "done"
        return models.ExtractTaskOut(
            id=row.id,
            work_id=row.work_id,
            title=row.title,
            state=cast(models.ExtractState, row.state),
            format=row.format,
            files_total=row.files_total,
            bytes_total=row.bytes_total,
            bytes_done=row.bytes_done,
            code=row.error_code,
            message=MESSAGES.get(row.error_code) if row.error_code else None,
            can_retry=row.state in ("failed", "cancelled", "interrupted")
            and row.error_code != "account_changed",
            location=str(final) if done and final else None,
            result_missing=bool(done and (final is None or not final.is_dir())),
            cleanup_failed=bool(row.cleanup_failed),
            created_at=row.created_at,
            finished_at=row.finished_at,
        )

    def tasks(self) -> models.ExtractionsOut:
        with self._engine.connect() as connection:
            rows = self._ordinary_rows(connection)
        return models.ExtractionsOut(
            tasks=[self._out(row) for row in rows],
            active_count=sum(1 for row in rows if row.state in _WORKING),
        )

    def _task(self, connection: Connection, task_id: str) -> Row[Any]:
        rows = self._ordinary_rows(connection, extract_tasks.c.id == task_id)
        if not rows:
            raise AtlasError("task_not_found", "找不到这个解压任务。", status=404)
        return rows[0]

    def _one(self, task_id: str) -> models.ExtractTaskOut:
        with self._engine.connect() as connection:
            return self._out(self._task(connection, task_id))

    # --- control ---

    def _sources(self, connection: Connection, work_id: str, fingerprint: str | None) -> list[str]:
        """The latest finished download of each file. A split work must be complete."""
        rows = connection.execute(
            select(download_tasks)
            .where(download_tasks.c.work_id == work_id, download_tasks.c.state == "done")
            .order_by(download_tasks.c.created_at)
        ).all()
        latest = {row.part_number: row for row in rows}
        if not latest:
            raise AtlasError("no_download", MESSAGES["no_download"], status=409)
        if any(row.account_fingerprint != fingerprint for row in latest.values()):
            raise AtlasError("account_changed", MESSAGES["account_changed"], status=409)
        counts = {row.part_count for row in latest.values() if row.part_count}
        if counts:
            needed = set(range(1, max(counts) + 1))
            if not needed <= set(latest):
                raise AtlasError("missing_parts", MESSAGES["missing_parts"], status=409)
        return [latest[number].id for number in sorted(latest)]

    def start(self, work_id: str, *, again: bool = False) -> models.ExtractionsOut:
        with self._engine.connect() as connection:
            work = get_ordinary_work(connection, work_id)
            account = accounts.get_account(connection)
            fingerprint = account.account_fingerprint if account else None
            sources = self._sources(connection, work_id, fingerprint)
        root = self._folders.works_root()
        with self._lock, writing(self._engine).begin() as connection:
            latest = connection.execute(
                select(extract_tasks)
                .where(extract_tasks.c.work_id == work_id)
                .order_by(extract_tasks.c.created_at.desc())
                .limit(1)
            ).first()
            if latest is not None and latest.state in _WORKING:
                return self.tasks()  # The same request twice is the same task.
            if (
                latest is not None
                and not again
                and latest.state in ("done", "not_needed")
                and json.loads(latest.source_task_ids) == sources
                and (latest.state == "not_needed" or (_final(latest) or Path("?")).is_dir())
            ):
                return self.tasks()
            now = _now()
            try:
                connection.execute(
                    extract_tasks.insert().values(
                        id=uuid.uuid4().hex,
                        work_id=work_id,
                        source_work_id=work.source_work_id,
                        account_fingerprint=fingerprint,
                        state="queued",
                        active_key=work_id,
                        source_task_ids=json.dumps(sources),
                        root_dir=str(root),
                        created_at=now,
                        updated_at=now,
                    )
                )
            except IntegrityError:
                raise AtlasError("extract_exists", "这部作品已经在解压了。", status=409) from None
        self._pump()
        return self.tasks()

    def flow_finished(self, work_id: str) -> None:
        """Called when a download the user asked to unpack has finished. A problem here must not
        spoil the finished download: the user can still start it by hand."""
        try:
            self.start(work_id)
        except AtlasError as error:
            logger.warning("unpacking after download did not start: %s", error.code)

    def retry(self, task_id: str) -> models.ExtractTaskOut:
        with self._lock, writing(self._engine).begin() as connection:
            row = self._task(connection, task_id)
            if row.error_code == "account_changed":
                raise AtlasError("account_changed", MESSAGES["account_changed"], status=409)
            if row.state in ("failed", "cancelled", "interrupted"):
                try:
                    with connection.begin_nested():
                        connection.execute(
                            update(extract_tasks)
                            .where(extract_tasks.c.id == row.id)
                            .values(
                                state="queued",
                                active_key=row.work_id,
                                attempt=row.attempt + 1,
                                error_code=None,
                                final_name=None,
                                bytes_done=0,
                                finished_at=None,
                                updated_at=_now(),
                            )
                        )
                except IntegrityError:
                    raise AtlasError(
                        "extract_exists", "这部作品已经在解压了。", status=409
                    ) from None
        self._pump()
        return self._one(task_id)

    def cancel(self, task_id: str) -> models.ExtractTaskOut:
        """A finished task stays finished; the download is never touched."""
        with self._lock:
            with self._engine.connect() as connection:
                row = self._task(connection, task_id)
            control = self._running.get(task_id)
            if control is not None:
                control.stop("cancel")
            elif row.state == "queued":
                self._write(row.id, row.attempt, state="cancelled", code="cancelled", ended=True)
        return self._one(task_id)

    def clear_finished(self) -> models.ExtractionsOut:
        """Forgets failed and cancelled records. Results and downloads are not touched."""
        with self._lock, writing(self._engine).begin() as connection:
            rows = self._ordinary_rows(
                connection, extract_tasks.c.state.in_(("cancelled", "failed", "interrupted"))
            )
            ids = [row.id for row in rows]
            connection.execute(delete(extract_tasks).where(extract_tasks.c.id.in_(ids)))
        return self.tasks()

    def open_folder(self, task_id: str) -> models.ExtractTaskOut:
        """Only ever the folder this finished task created; the request cannot name a path."""
        with self._engine.connect() as connection:
            row = self._task(connection, task_id)
        final = _final(row)
        if row.state != "done" or final is None:
            raise AtlasError("task_not_finished", "这个任务还没有完成。", status=409)
        self._folders.open_path(final)
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
                    select(extract_tasks)
                    # A worker only marks its task once it is running, so one just started still
                    # reads as queued: without this it would be started a second time.
                    .where(
                        extract_tasks.c.state == "queued",
                        extract_tasks.c.id.not_in(list(self._running)),
                    )
                    .order_by(extract_tasks.c.created_at)
                    .limit(room)
                ).all()
            for row in rows:
                control = _Control(threading.Event())
                self._running[row.id] = control
                thread = threading.Thread(
                    target=self._run, args=(row, control), name="extract", daemon=True
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
            if values["state"] not in _WORKING:
                changes["active_key"] = None
        if ended:
            changes["finished_at"] = _now()
        with writing(self._engine).begin() as connection:
            result = connection.execute(
                update(extract_tasks)
                .where(extract_tasks.c.id == task_id, extract_tasks.c.attempt == attempt)
                .values(**changes)
            )
        return bool(result.rowcount)

    def _run(self, row: Row[Any], control: _Control) -> None:
        try:
            self._execute(row, control)
        except _Stop as stop:
            self._remove_staging(row)
            self._write(row.id, row.attempt, state=stop.state, code=stop.code, ended=True)
        except Exception as error:  # noqa: BLE001 - must end the task; type only, no data.
            logger.error("extraction failed: %s", type(error).__name__)
            self._remove_staging(row)
            self._write(row.id, row.attempt, state="failed", code="unexpected", ended=True)
        finally:
            with self._lock:
                self._running.pop(row.id, None)
                self._threads.pop(row.id, None)
            self._pump()

    @staticmethod
    def _check(control: _Control) -> None:
        if control.reason == "cancel":
            raise _Stop("cancelled", "cancelled")
        if control.reason == "shutdown":
            raise _Stop("interrupted", "interrupted")

    def _inputs(self, row: Row[Any], control: _Control) -> list[Path]:
        """Each file must still be the one downloaded: same size and hash, same place."""
        ids = json.loads(row.source_task_ids)
        with self._engine.connect() as connection:
            account = accounts.get_account(connection)
            sources = {
                source.id: source
                for source in connection.execute(
                    select(download_tasks).where(download_tasks.c.id.in_(ids))
                ).all()
            }
        if (account.account_fingerprint if account else None) != row.account_fingerprint:
            raise _Stop("failed", "account_changed")
        paths = []
        for task_id in ids:
            source = sources.get(task_id)
            if source is None or source.state != "done" or not source.file_name:
                raise _Stop("failed", "input_changed")
            folder = Path(source.target_dir)
            path = folder / source.file_name
            try:
                if (
                    path.resolve().parent != folder.resolve()
                    or path.stat().st_size != source.bytes_done
                    or _hash_file(path, lambda: self._check(control)) != source.sha256
                ):
                    raise _Stop("failed", "input_changed")
            except OSError:
                raise _Stop("failed", "input_changed") from None
            paths.append(path)
        return paths

    def _read(self, first: Path) -> tuple[Listing, str] | None:
        """The listing and the engine to use, or None if this is not an archive. What the file
        is comes from its content; its name has no say."""
        kind = sniff(first)
        tool = self._find_tool()
        if kind == "zip":
            try:
                return list_zip(first, self._limits), "zip"
            except ArchiveProblem as problem:
                if problem.code != "unsupported_format" or tool is None:
                    raise
            return tool.list(first, self._limits), "tool"
        if kind in ("rar", "7z"):
            if tool is None:
                raise ArchiveProblem("tool_missing")
            return tool.list(first, self._limits), "tool"
        if kind == "executable":
            # Either a self-extracting archive or an ordinary program. Only 7-Zip can tell, and
            # it reads the file as data: nothing here runs it.
            if tool is None:
                raise ArchiveProblem("tool_missing")
            if tool.kind(first) is None:
                return None
            return tool.list(first, self._limits), "tool"
        return None

    def _execute(self, row: Row[Any], control: _Control) -> None:
        self._write(row.id, row.attempt, state="checking")
        inputs = self._inputs(row, control)
        self._check(control)
        root = Path(row.root_dir)
        if not root.is_dir():
            raise _Stop("failed", "folder_missing")
        try:
            read = self._read(inputs[0])
            # Not an archive: the file itself is the work, and it goes to the same place.
            listing, engine = read if read is not None else (_as_files(inputs), "file")
            self._write(
                row.id,
                row.attempt,
                format=listing.kind,
                files_total=listing.files,
                bytes_total=listing.total_bytes,
            )
            if listing.total_bytes > self._free_space(root):
                raise ArchiveProblem("disk_full")
            self._check(control)
            staging = _staging(row)
            staging.mkdir()
            self._write(row.id, row.attempt, state="extracting")
            self._unpack(row, control, inputs, staging, listing, engine)
            self._check(control)
            verify_output(staging, listing)
        except ArchiveProblem as problem:
            raise _Stop("failed", problem.code) from None
        except Stopped:
            self._check(control)
            raise _Stop("interrupted", "interrupted") from None
        except OSError as error:
            full = getattr(error, "winerror", None) in (39, 112)
            raise _Stop("failed", "disk_full" if full else "write_failed") from None
        self._commit(row, control, listing)

    def _unpack(
        self,
        row: Row[Any],
        control: _Control,
        sources: list[Path],
        staging: Path,
        listing: Listing,
        engine: str,
    ) -> None:
        last = [0.0]

        def report(done: int) -> None:
            if time.monotonic() - last[0] >= PROGRESS_INTERVAL:
                self._write(row.id, row.attempt, bytes_done=done)
                last[0] = time.monotonic()

        def check() -> None:
            if control.reason:
                raise Stopped

        progress: Progress = report
        if engine == "file":
            _copy_files(sources, staging, progress, check)
        elif engine == "zip":
            extract_zip(sources[0], staging, self._limits, progress, check)
        else:
            tool = self._find_tool()
            if tool is None:
                raise ArchiveProblem("tool_missing")
            tool.extract(sources[0], staging, self._limits, progress, check)
        self._write(row.id, row.attempt, bytes_done=listing.total_bytes)

    def _commit(self, row: Row[Any], control: _Control, listing: Listing) -> None:
        """The commit point. A cancel that arrives first wins; after this the result is final.
        The name is recorded before the rename, for `recover`."""
        root = Path(row.root_dir)
        with self._engine.connect() as connection:
            work = connection.execute(
                select(works.c.kind, works.c.raw_kind, works.c.maker, works.c.title).where(
                    works.c.id == row.work_id
                )
            ).one()
        kind, maker, title = work_folder(
            work.kind,
            work.raw_kind,
            work.maker,
            work.title,
            safe_file_name(row.source_work_id, "work"),
        )
        parent = root / kind / maker
        try:
            parent.mkdir(parents=True, exist_ok=True)
            # A link somewhere along the way must not lead the result out of the chosen folder.
            if not parent.resolve().is_relative_to(root.resolve()):
                raise _Stop("failed", "folder_invalid")
        except OSError:
            raise _Stop("failed", "write_failed") from None
        with self._lock:
            self._check(control)
            for number in range(1, 1000):
                name = title if number == 1 else f"{title} ({number})"
                if os.path.lexists(parent / name):
                    continue
                self._write(
                    row.id, row.attempt, state="committing", final_name=f"{kind}/{maker}/{name}"
                )
                try:
                    os.rename(_staging(row), parent / name)
                except FileExistsError:
                    continue
                except OSError:
                    raise _Stop("failed", "write_failed") from None
                self._write(
                    row.id,
                    row.attempt,
                    state="done",
                    ended=True,
                    bytes_done=listing.total_bytes,
                )
                return
        raise _Stop("failed", "write_failed")

    def _remove_staging(self, row: Row[Any]) -> None:
        """Only ever this task's own folder, by a name built from its ID."""
        staging = _staging(row)
        if not staging.name.startswith(_STAGING_PREFIX) or not staging.exists():
            return
        try:
            shutil.rmtree(staging)
        except OSError:
            logger.warning("could not remove an unpacking folder")
            self._write(row.id, row.attempt, cleanup_failed=1)
