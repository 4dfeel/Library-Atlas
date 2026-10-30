"""Where downloads go. Only records and checks folders the user chose: it does not scan
disks or move files, and a chosen folder that has gone missing is reported, never recreated
(it may be an unplugged drive).
"""

import os
import tempfile
import threading
from pathlib import Path

from sqlalchemy import Engine

from app.adapters.system.folder_dialog import FolderOpener, FolderPicker
from app.api import models
from app.core.config import Settings
from app.core.errors import AtlasError
from app.db.engine import writing
from app.repositories import app_settings

_DEFAULT_ARCHIVES = "Archives"
_KEYS: dict[models.FolderKind, str] = {
    "library": "folder.library",
    "download_cache": "folder.download_cache",
}


def _invalid(message: str) -> AtlasError:
    return AtlasError("folder_invalid", message, status=422)


def _protected_roots() -> list[Path]:
    roots = [os.environ.get(name) for name in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)")]
    return [Path(root) for root in roots if root]


class FolderService:
    def __init__(
        self, engine: Engine, settings: Settings, picker: FolderPicker, opener: FolderOpener
    ) -> None:
        self._engine = engine
        self._settings = settings
        self._picker = picker
        self._opener = opener
        self._picking = threading.Lock()

    def _default(self, kind: models.FolderKind) -> Path | None:
        # Works go where the user decides. Archives follow them unless told otherwise.
        if kind != "download_cache":
            return None
        library = self._chosen("library")
        return library / _DEFAULT_ARCHIVES if library else None

    def _chosen(self, kind: models.FolderKind) -> Path | None:
        with self._engine.connect() as connection:
            value = app_settings.get(connection, _KEYS[kind])
        return Path(value) if value else None

    def _describe(self, kind: models.FolderKind) -> models.FolderOut:
        chosen = self._chosen(kind)
        path = chosen or self._default(kind)
        if path is None:
            status: models.FolderStatus = "not_set"
        elif chosen is None or path.is_dir():
            status = "ok"  # A default folder is created when first needed.
        else:
            status = "missing"
        return models.FolderOut(
            kind=kind, path=str(path) if path else None, is_default=chosen is None, status=status
        )

    def folders(self) -> models.FoldersOut:
        return models.FoldersOut(folders=[self._describe(kind) for kind in _KEYS])

    def describe_library(self) -> models.FolderOut:
        return self._describe("library")

    def works_root(self) -> Path:
        """Where works go once they are ready to use."""
        library = self._chosen("library")
        if library is None:
            raise AtlasError("folder_not_set", "请先选择作品文件夹。", status=409)
        if not library.is_dir():
            raise AtlasError(
                "folder_missing", "作品文件夹现在不存在，可能是硬盘没有连接。", status=409
            )
        return library

    def download_targets(self) -> tuple[Path, Path]:
        """The works folder, and where downloaded archives are kept: a folder of the user's
        choosing, or by default inside the works folder, so they land on the same drive."""
        library = self.works_root()
        chosen = self._chosen("download_cache")
        if chosen is not None and not chosen.is_dir():
            raise AtlasError(
                "folder_missing", "压缩包文件夹现在不存在，可能是硬盘没有连接。", status=409
            )
        archives = chosen or library / _DEFAULT_ARCHIVES
        try:
            archives.mkdir(exist_ok=True)
        except OSError:
            raise AtlasError(
                "write_failed", "无法写入作品文件夹，请检查权限。", status=409
            ) from None
        return library, archives

    def open_path(self, path: Path) -> None:
        """For a folder a finished task wrote to; callers never pass request data."""
        if not path.is_dir():
            raise AtlasError("folder_missing", "这个文件夹现在不存在。", status=409)
        try:
            self._opener.open(path)
        except OSError:
            raise AtlasError("folder_open_failed", "无法打开这个文件夹。", status=500) from None

    def _validate(self, kind: models.FolderKind, raw: str) -> Path:
        path = Path(raw.strip())
        if not path.is_absolute():
            raise _invalid("请提供完整的文件夹路径。")
        if not path.is_dir():
            raise _invalid("这个文件夹不存在。请先创建，或用“更改”选择。")
        resolved = path.resolve()
        data_dir = self._settings.data_dir.resolve()
        if resolved == data_dir or resolved.is_relative_to(data_dir):
            raise _invalid("不能使用 Atlas 自己的数据目录。")
        for root in _protected_roots():
            if resolved == root.resolve() or resolved.is_relative_to(root.resolve()):
                raise _invalid("不能使用系统文件夹。")
        for other in _KEYS:
            if other == kind:
                continue
            current = self._chosen(other)
            if current is not None and current.resolve() == resolved:
                raise _invalid("作品文件夹和压缩包文件夹不能是同一个文件夹。")
        try:
            with tempfile.TemporaryFile(dir=resolved):
                pass
        except OSError:
            raise _invalid("没有这个文件夹的写入权限。") from None
        return resolved

    def set_folder(self, kind: models.FolderKind, raw: str) -> models.FoldersOut:
        path = self._validate(kind, raw)
        with writing(self._engine).begin() as connection:
            app_settings.put(connection, _KEYS[kind], str(path))
        return self.folders()

    def pick(self, kind: models.FolderKind) -> models.FoldersOut:
        """Blocks until the user closes the dialog; cancelling changes nothing."""
        if not self._picking.acquire(blocking=False):
            raise AtlasError("picker_open", "文件夹选择窗口已经打开了。", status=409)
        try:
            current = self._chosen(kind)
            chosen = self._picker.pick(current if current and current.is_dir() else None)
        except OSError:
            raise AtlasError(
                "picker_failed", "无法打开文件夹选择窗口，可以直接输入路径。", status=500
            ) from None
        finally:
            self._picking.release()
        return self.set_folder(kind, str(chosen)) if chosen else self.folders()

    def open_folder(self, kind: models.FolderKind) -> models.FoldersOut:
        """Only ever opens a registered folder; the request cannot name a path."""
        chosen = self._chosen(kind)
        path = chosen or self._default(kind)
        if path is None:
            raise AtlasError("folder_not_set", "还没有设置这个文件夹。", status=409)
        if chosen is None:
            path.mkdir(parents=True, exist_ok=True)
        if not path.is_dir():
            raise AtlasError(
                "folder_missing", "这个文件夹现在不存在，可能是硬盘没有连接。", status=409
            )
        try:
            self._opener.open(path)
        except OSError:
            raise AtlasError("folder_open_failed", "无法打开这个文件夹。", status=500) from None
        return self.folders()
