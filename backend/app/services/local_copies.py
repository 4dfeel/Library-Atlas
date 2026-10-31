"""Where a work's files are on this computer. Mostly a record: uninstalling is the one thing here
that moves files, and only to the Recycle Bin. Otherwise adding or removing a copy never moves
or deletes anything, and nothing here runs a program except `launch`, on the user's own click.

A request can only name a saved copy to act on, never a command or a path to run. Paths are
checked when saved and again when used, because folders go offline and files get replaced.
"""

import os
import re
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from sqlalchemy import Connection, Engine, Row, delete, select, update

from app.adapters.system.archives import ArchiveProblem, safe_parts
from app.api import models
from app.core.config import Settings
from app.core.errors import AtlasError
from app.db.engine import writing
from app.db.schema import (
    game_updates,
    local_copies,
    personal_records,
    scan_items,
    scan_roots,
    works,
)
from app.domain.local_files import entry_candidates, single_entry
from app.repositories.works import ORDINARY, get_ordinary_work
from app.services.folders import FolderService, is_protected

_DOUBLE_CLICK_SECONDS = 3.0
_MAX_ARGUMENTS = 20
_MAX_ARGUMENT = 500
MESSAGES = {
    "ok": "可以启动",
    "no_entry": "还没有选择主程序。",
    "root_missing": "这个文件夹现在不存在，可能被移动了。",
    "offline": "这个文件夹所在的硬盘现在没有连接。",
    "entry_missing": "主程序不在了，请重新选择。",
}


class Launcher(Protocol):
    def launch(self, program: Path, arguments: list[str], working: Path) -> None: ...


class Shell(Protocol):
    def recycle(self, path: Path) -> None: ...

    def desktop(self) -> Path: ...

    def write_shortcut(
        self,
        link: Path,
        target: Path,
        arguments: list[str],
        working: Path | None,
        icon: Path | None,
    ) -> None: ...


_UPDATE_HOLDS = (
    "queued",
    "backing_up",
    "downloading",
    "unpacking",
    "replacing",
    "cleaning",
    "awaiting_confirmation",
)
# `<library>/<type>/<maker>/<work>`: anything above the work is shared with other works.
_LIBRARY_LAYERS = 3
_MAX_COUNTED = 200_000
_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _in_use(program: Path) -> bool:
    """Windows will not let a running program be opened for writing. Not everything a game holds
    is covered, so the Recycle Bin's own refusal is the other half of this."""
    try:
        with program.open("r+b"):
            return False
    except PermissionError:
        return True
    except OSError:
        return False


def _measure(root: Path) -> tuple[int, int, bool]:
    """Files and bytes, without following links out of the folder."""
    files = size = 0
    stack = [str(root)]
    while stack:
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    if entry.is_symlink() or entry.is_junction():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                        continue
                    files += 1
                    if files > _MAX_COUNTED:
                        return files, size, False
                    size += entry.stat(follow_symlinks=False).st_size
        except OSError:
            return files, size, False
    return files, size, True


def _invalid(message: str) -> AtlasError:
    return AtlasError("copy_invalid", message, status=422)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _key(path: Path) -> str:
    return str(path).casefold()


def _inside(root: Path, relative: str) -> Path:
    """A path under the copy's folder, judged as Windows would read it, links included."""
    try:
        target = root.joinpath(*safe_parts(relative))
    except ArchiveProblem:
        raise _invalid("路径必须在这个文件夹内。") from None
    if not target.resolve().is_relative_to(root.resolve()):
        raise _invalid("路径必须在这个文件夹内。")
    return target


class LocalCopies:
    def __init__(
        self,
        engine: Engine,
        settings: Settings,
        folders: FolderService,
        launcher: Launcher,
        shell: Shell,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._engine = engine
        self._settings = settings
        self._folders = folders
        self._launcher = launcher
        self._shell = shell
        # Told after a game is handed to Windows. It must not be able to fail the launch.
        self.on_launched: Callable[[str, Path], None] | None = None
        self._clock = clock
        self._lock = threading.Lock()
        self._last_launch: dict[str, float] = {}

    # --- reading ---

    @staticmethod
    def _status(row: Row[Any]) -> str:
        root = Path(row.root_path)
        if not root.is_dir():
            return "offline" if not Path(root.anchor or ".").exists() else "root_missing"
        if not row.entry_path:
            return "no_entry"
        return "ok" if (root / row.entry_path).is_file() else "entry_missing"

    def _out(self, row: Row[Any]) -> models.LocalCopyOut:
        status = self._status(row)
        return models.LocalCopyOut(
            id=row.id,
            work_id=row.work_id,
            root=row.root_path,
            entry=row.entry_path,
            working=row.working_path,
            arguments=row.arguments or [],
            label=row.label,
            is_default=bool(row.is_default),
            origin=cast(models.CopyOrigin, row.origin),
            status=cast(models.CopyStatus, status),
            message=MESSAGES[status],
        )

    def copies(self, work_id: str) -> models.LocalCopiesOut:
        with self._engine.connect() as connection:
            get_ordinary_work(connection, work_id)
            rows = connection.execute(
                select(local_copies)
                .where(local_copies.c.work_id == work_id)
                .order_by(local_copies.c.is_default.desc(), local_copies.c.created_at)
            ).all()
        return models.LocalCopiesOut(copies=[self._out(row) for row in rows])

    def _copy(self, connection: Connection, copy_id: str) -> Row[Any]:
        """Through the ordinary scope: a hidden work's copy is as absent as the work."""
        row = connection.execute(
            select(local_copies)
            .join(personal_records, personal_records.c.work_id == local_copies.c.work_id)
            .where(local_copies.c.id == copy_id, ORDINARY)
        ).first()
        if row is None:
            raise AtlasError("copy_not_found", "找不到这个本地文件关联。", status=404)
        return row

    # --- saving ---

    def _root(self, raw: str) -> Path:
        path = Path(raw.strip())
        if not path.is_absolute():
            raise _invalid("请提供完整的文件夹路径。")
        if not path.is_dir():
            raise _invalid("这个文件夹不存在。")
        resolved = path.resolve()
        data_dir = self._settings.data_dir.resolve()
        if resolved == data_dir or resolved.is_relative_to(data_dir) or is_protected(resolved):
            raise _invalid("不能关联系统文件夹或 Atlas 自己的数据目录。")
        return resolved

    @staticmethod
    def _arguments(values: list[str]) -> list[str]:
        if len(values) > _MAX_ARGUMENTS or any(
            len(value) > _MAX_ARGUMENT or "\x00" in value for value in values
        ):
            raise _invalid("启动参数太多或太长。")
        return values

    def _entry(self, root: Path, relative: str | None) -> str | None:
        if not relative:
            return None
        target = _inside(root, relative)
        # Only a program itself: a script, shortcut or installer chain is not known to be safe.
        if target.suffix.lower() != ".exe":
            raise _invalid("目前只支持 .exe 主程序。")
        if not target.is_file():
            raise _invalid("找不到这个主程序。")
        return target.relative_to(root).as_posix()

    def _working(self, root: Path, relative: str | None) -> str | None:
        if not relative:
            return None
        target = _inside(root, relative)
        if not target.is_dir():
            raise _invalid("找不到这个工作目录。")
        return target.relative_to(root).as_posix()

    def preview(self, raw: str) -> models.CopyPreviewOut:
        """What a folder offers, read from names only. Nothing in it is opened or run."""
        root = self._root(raw)
        candidates = entry_candidates(root)
        return models.CopyPreviewOut(
            root=str(root),
            entries=[
                models.CopyEntryOut(path=item.path, likely_helper=item.helper)
                for item in candidates
            ],
            suggested=single_entry(candidates),
        )

    def add(self, work_id: str, body: models.LocalCopyIn) -> models.LocalCopiesOut:
        root = self._root(body.root)
        entry = self._entry(root, body.entry)
        working = self._working(root, body.working)
        arguments = self._arguments(body.arguments)
        self._insert(
            work_id,
            root,
            entry=entry,
            working=working,
            arguments=arguments,
            label=(body.label or "").strip() or None,
            origin="manual",
            make_default=body.make_default,
        )
        return self.copies(work_id)

    def _insert(
        self,
        work_id: str,
        root: Path,
        *,
        entry: str | None,
        working: str | None = None,
        arguments: list[str] | None = None,
        label: str | None = None,
        origin: str,
        make_default: bool = False,
        batch_id: str | None = None,
    ) -> str | None:
        """None when this work already has this folder: saving twice is one copy."""
        with writing(self._engine).begin() as connection:
            get_ordinary_work(connection, work_id)
            existing = connection.execute(
                select(local_copies.c.id).where(
                    local_copies.c.work_id == work_id, local_copies.c.root_key == _key(root)
                )
            ).first()
            if existing is not None:
                return None
            first = (
                connection.execute(
                    select(local_copies.c.id).where(local_copies.c.work_id == work_id)
                ).first()
                is None
            )
            if make_default and not first:
                connection.execute(
                    update(local_copies)
                    .where(local_copies.c.work_id == work_id)
                    .values(is_default=0)
                )
            copy_id = uuid.uuid4().hex
            now = _now()
            connection.execute(
                local_copies.insert().values(
                    id=copy_id,
                    work_id=work_id,
                    root_path=str(root),
                    root_key=_key(root),
                    entry_path=entry,
                    working_path=working,
                    arguments=arguments or [],
                    label=label,
                    is_default=1 if first or make_default else 0,
                    origin=origin,
                    batch_id=batch_id,
                    created_at=now,
                    updated_at=now,
                )
            )
        return copy_id

    def add_found(
        self, work_id: str, root: Path, *, origin: str, batch_id: str | None = None
    ) -> str | None:
        """For a folder Atlas itself found or made. The program is chosen only when there is
        exactly one plausible candidate; otherwise the user chooses. Nothing is run."""
        candidates = entry_candidates(root)
        # A release renames its folder: the copy that is found takes over from one that has gone.
        with self._engine.connect() as connection:
            default = connection.execute(
                select(local_copies.c.root_path).where(
                    local_copies.c.work_id == work_id, local_copies.c.is_default == 1
                )
            ).scalar()
        return self._insert(
            work_id,
            root,
            entry=single_entry(candidates),
            origin=origin,
            make_default=origin == "unpacked"
            or (default is not None and not Path(default).is_dir()),
            batch_id=batch_id,
        )

    def record_unpacked(self, work_id: str, root: Path) -> None:
        self.add_found(work_id, root, origin="unpacked")

    def update_copy(self, copy_id: str, body: models.LocalCopyUpdate) -> models.LocalCopyOut:
        with self._engine.connect() as connection:
            row = self._copy(connection, copy_id)
        root = Path(row.root_path)
        values: dict[str, Any] = {"updated_at": _now()}
        fields = body.model_fields_set
        if "root" in fields and body.root:
            root = self._root(body.root)  # Relocating: the user points at the new place.
            values.update(root_path=str(root), root_key=_key(root))
        if "entry" in fields:
            values["entry_path"] = self._entry(root, body.entry)
        if "working" in fields:
            values["working_path"] = self._working(root, body.working)
        if "arguments" in fields and body.arguments is not None:
            values["arguments"] = self._arguments(body.arguments)
        if "label" in fields:
            values["label"] = (body.label or "").strip() or None
        with writing(self._engine).begin() as connection:
            connection.execute(
                update(local_copies).where(local_copies.c.id == copy_id).values(**values)
            )
        with self._engine.connect() as connection:
            return self._out(self._copy(connection, copy_id))

    def set_default(self, copy_id: str) -> models.LocalCopiesOut:
        with writing(self._engine).begin() as connection:
            row = self._copy(connection, copy_id)
            connection.execute(
                update(local_copies)
                .where(local_copies.c.work_id == row.work_id)
                .values(is_default=0)
            )
            connection.execute(
                update(local_copies).where(local_copies.c.id == copy_id).values(is_default=1)
            )
        return self.copies(row.work_id)

    def remove(self, copy_id: str) -> models.LocalCopiesOut:
        """Forgets the record. The folder and everything in it stay exactly where they are."""
        with writing(self._engine).begin() as connection:
            row = self._copy(connection, copy_id)
            connection.execute(delete(local_copies).where(local_copies.c.id == copy_id))
            if row.is_default:
                other = connection.execute(
                    select(local_copies.c.id)
                    .where(local_copies.c.work_id == row.work_id)
                    .order_by(local_copies.c.created_at)
                    .limit(1)
                ).scalar()
                if other:
                    connection.execute(
                        update(local_copies).where(local_copies.c.id == other).values(is_default=1)
                    )
        return self.copies(row.work_id)

    # --- uninstalling ---

    def _uninstall_block(self, row: Row[Any]) -> str | None:
        """Why this folder must not go. Only one work's own folder ever may: never something that
        holds other works, the library itself or a place the user chose for Atlas."""
        raw = Path(row.root_path)
        if not raw.is_dir():
            return "这个文件夹现在不存在或硬盘没有连接。"
        if raw.is_symlink() or raw.is_junction():
            return "这是一个链接，不是作品本身的文件夹。"
        root = raw.resolve()
        data_dir = self._settings.data_dir.resolve()
        if is_protected(root) or root == data_dir or data_dir.is_relative_to(root):
            return "这是系统文件夹，不能卸载。"
        if root.is_relative_to(data_dir):
            return "这是 Atlas 自己的数据目录，不能卸载。"
        for chosen in self._folders.chosen_folders():
            place = chosen.resolve()
            if root == place or place.is_relative_to(root):
                return "这是你为 Atlas 选择的文件夹，不能卸载。"
        with self._engine.connect() as connection:
            libraries = connection.execute(select(scan_roots.c.path)).scalars().all()
            others = connection.execute(
                select(local_copies.c.root_path).where(local_copies.c.id != row.id)
            ).scalars()
            for other in others:
                place = Path(other).resolve()
                if place == root or place.is_relative_to(root) or root.is_relative_to(place):
                    return "这个文件夹和另一个关联的文件夹重叠，不能卸载。"
            updating = connection.execute(
                select(game_updates.c.id).where(
                    game_updates.c.work_id == row.work_id, game_updates.c.state.in_(_UPDATE_HOLDS)
                )
            ).first()
        for library in libraries:
            place = Path(library).resolve()
            if place.is_relative_to(root):
                return "这个文件夹包含整个作品库，不能卸载。"
            if root.is_relative_to(place) and len(root.relative_to(place).parts) < _LIBRARY_LAYERS:
                return "这是作品库的一层目录，里面可能有别的作品，不能卸载。"
        if updating is not None:
            return "这部作品正在更新，请等更新结束。"
        if row.entry_path:
            program = _inside(root, row.entry_path)
            if program.is_file() and _in_use(program):
                return "主程序正在运行。请先关闭游戏。"
        return None

    def uninstall_preview(self, copy_id: str) -> models.UninstallPreview:
        with self._engine.connect() as connection:
            row = self._copy(connection, copy_id)
        blocked = self._uninstall_block(row)
        files, size, complete = _measure(Path(row.root_path)) if blocked is None else (0, 0, True)
        return models.UninstallPreview(
            root=row.root_path, files=files, size_bytes=size, complete=complete, blocked=blocked
        )

    def uninstall(self, copy_id: str, body: models.UninstallIn) -> models.LocalCopiesOut:
        """To the Recycle Bin, so it can be got back, and only the folder the user was shown. The
        record goes only once the folder really has. Their notes, ratings and collections stay."""
        with self._engine.connect() as connection:
            row = self._copy(connection, copy_id)
        if body.confirm_root != row.root_path:
            raise AtlasError("uninstall_changed", "文件夹已经变了，请重新确认。", status=409)
        blocked = self._uninstall_block(row)
        if blocked is not None:
            raise AtlasError("uninstall_refused", blocked, status=409)
        try:
            self._shell.recycle(Path(row.root_path))
        except OSError:
            raise AtlasError(
                "uninstall_failed",
                "没能移到回收站。可能有文件正在使用，或路径太长。什么都没有删除。",
                status=409,
            ) from None
        self.remove(copy_id)
        with writing(self._engine).begin() as connection:
            # A folder got back from the bin should be found again by the next scan.
            connection.execute(delete(scan_items).where(scan_items.c.path_key == row.root_key))
            left = connection.execute(
                select(local_copies.c.id).where(local_copies.c.work_id == row.work_id).limit(1)
            ).first()
            if left is None:
                connection.execute(
                    update(works).where(works.c.id == row.work_id).values(local_state="absent")
                )
        return self.copies(row.work_id)

    # --- shortcuts ---

    def shortcut(self, copy_id: str) -> models.ShortcutOut:
        """A game's shortcut starts the game; anything else's opens its folder. Never replaces a
        file already on the desktop."""
        with self._engine.connect() as connection:
            row = self._copy(connection, copy_id)
            work = connection.execute(
                select(works.c.kind, works.c.title).where(works.c.id == row.work_id)
            ).one()
        root = Path(row.root_path)
        status = self._status(row)
        if work.kind == "game":
            if status != "ok":
                raise AtlasError(f"copy_{status}", MESSAGES[status], status=409)
            program = _inside(root, row.entry_path)
            working = _inside(root, row.working_path) if row.working_path else program.parent
            target, arguments, start_in, icon = program, list(row.arguments or []), working, program
        else:
            if not root.is_dir():
                raise AtlasError("copy_root_missing", MESSAGES["root_missing"], status=409)
            target, arguments, start_in, icon = root, [], None, None
        name = _UNSAFE_NAME.sub(" ", work.title).strip(" .")[:80].strip(" .") or "作品"
        try:
            desktop = self._shell.desktop()
            link = desktop / f"{name}.lnk"
            attempt = 2
            while link.exists():
                link = desktop / f"{name} ({attempt}).lnk"
                attempt += 1
            self._shell.write_shortcut(link, target, arguments, start_in, icon)
        except OSError:
            raise AtlasError("shortcut_failed", "没能创建快捷方式。", status=409) from None
        return models.ShortcutOut(created=True)

    def choose_folder(self) -> models.ChosenFolderOut:
        chosen = self._folders.choose()
        return models.ChosenFolderOut(path=str(chosen) if chosen else None)

    # --- acting ---

    def open_folder(self, copy_id: str) -> models.LocalCopyOut:
        with self._engine.connect() as connection:
            row = self._copy(connection, copy_id)
        self._folders.open_path(Path(row.root_path))
        return self._out(row)

    def launch(self, copy_id: str) -> models.LaunchOut:
        """Only ever on a click. It can say the program was handed to Windows; whether the game
        then loads is something Atlas cannot see, and does not claim."""
        with self._engine.connect() as connection:
            row = self._copy(connection, copy_id)
            kind = connection.execute(
                select(works.c.kind).where(works.c.id == row.work_id)
            ).scalar()
        if kind != "game":
            raise AtlasError("launch_unsupported", "只有游戏可以启动。", status=409)
        status = self._status(row)
        if status != "ok":
            raise AtlasError(f"copy_{status}", MESSAGES[status], status=409)
        root = Path(row.root_path)
        program = _inside(root, row.entry_path)
        if program.suffix.lower() != ".exe":
            raise AtlasError("copy_entry_missing", MESSAGES["entry_missing"], status=409)
        working = _inside(root, row.working_path) if row.working_path else program.parent
        if not working.is_dir():
            raise AtlasError("launch_failed", "工作目录不存在，请编辑关联。", status=409)
        with self._lock:
            now = self._clock()
            if now - self._last_launch.get(copy_id, -_DOUBLE_CLICK_SECONDS) < _DOUBLE_CLICK_SECONDS:
                return models.LaunchOut(submitted=False, repeated=True)
            self._last_launch[copy_id] = now
        try:
            self._launcher.launch(program, list(row.arguments or []), working)
            if self.on_launched is not None:
                self.on_launched(row.work_id, program)
        except OSError as error:
            denied = isinstance(error, PermissionError) or getattr(error, "winerror", 0) in (
                5,
                740,
            )
            raise AtlasError(
                "launch_failed",
                "没有权限启动这个程序。Atlas 不会自动提权。"
                if denied
                else "无法启动这个程序，它可能缺少依赖或不是有效的程序。",
                status=409,
            ) from None
        return models.LaunchOut(submitted=True)
