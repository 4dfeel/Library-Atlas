"""The two things only Windows' own shell can do: the Recycle Bin and a real shortcut.

Both go through the API with the path as data, never through a command line.
"""

import ctypes
import subprocess
import uuid
from ctypes import wintypes
from pathlib import Path
from typing import Any

from app.domain.save_hints import KnownFolders

_FO_DELETE = 3
_FOF_SILENT = 0x0004
_FOF_NOCONFIRMATION = 0x0010
_FOF_ALLOWUNDO = 0x0040
_FOF_NOERRORUI = 0x0400
# With the flag above, Windows still asks before anything would be destroyed rather than recycled:
# a folder too large for the bin, or a drive without one.
_FOF_WANTNUKEWARNING = 0x4000
_S_OK_FALSE = 1

_CLSID_SHELL_LINK = "00021401-0000-0000-C000-000000000046"
_IID_SHELL_LINK = "000214F9-0000-0000-C000-000000000046"
_IID_PERSIST_FILE = "0000010B-0000-0000-C000-000000000046"
_FOLDERID_DESKTOP = "B4BFCC3A-DB2C-424C-B029-7FE99A87C641"
_CLSCTX_INPROC_SERVER = 1
_COINIT_APARTMENTTHREADED = 2
# Positions in each interface's method table.
_RELEASE = 2
_SET_WORKING_DIRECTORY = 9
_SET_ARGUMENTS = 11
_SET_ICON_LOCATION = 17
_SET_PATH = 20
_QUERY_INTERFACE = 0
_SAVE = 6


class _FileOperation(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", wintypes.WORD),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", wintypes.LPVOID),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def recycle(path: Path) -> None:
    """Raises OSError unless the folder has really left its place."""
    paths = ctypes.create_unicode_buffer(f"{path}\0\0")
    operation = _FileOperation(
        hwnd=None,
        wFunc=_FO_DELETE,
        pFrom=ctypes.cast(paths, wintypes.LPCWSTR),
        pTo=None,
        fFlags=_FOF_ALLOWUNDO
        | _FOF_NOCONFIRMATION
        | _FOF_SILENT
        | _FOF_NOERRORUI
        | _FOF_WANTNUKEWARNING,
    )
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    if result != 0 or operation.fAnyOperationsAborted or path.exists():
        raise OSError("the folder was not moved to the Recycle Bin")


def _guid(text: str) -> ctypes.Array[ctypes.c_char]:
    return ctypes.create_string_buffer(uuid.UUID(text).bytes_le, 16)


def _method(pointer: ctypes.c_void_p, index: int, *arguments: type) -> Any:
    table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    prototype = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *arguments)
    return prototype(table[index])


def _known_folder(folder_id: str) -> Path:
    """Asked of Windows: these folders are often not where their names suggest."""
    found = wintypes.LPWSTR()
    result = ctypes.windll.shell32.SHGetKnownFolderPath(
        _guid(folder_id), 0, None, ctypes.byref(found)
    )
    if result != 0:
        raise OSError("that folder is not known")
    try:
        return Path(found.value or "")
    finally:
        ctypes.windll.ole32.CoTaskMemFree(found)


def desktop_folder() -> Path:
    return _known_folder(_FOLDERID_DESKTOP)


def user_folders() -> KnownFolders:
    return KnownFolders(
        _known_folder("F1B32785-6FBA-4FCF-9D55-7B8E7F157091"),
        _known_folder("A520A1A4-1780-4FF6-BD18-167343C5AF16"),
        _known_folder("3EB685DB-65F9-4CF6-A03A-E3EF65729F3D"),
        _known_folder("FDD39AD0-238F-46AF-ADB4-6C85480369C7"),
        _known_folder("4C5C32FF-BB9D-43B0-B5B4-2D72E54EAAA4"),
    )


def write_shortcut(
    link: Path, target: Path, arguments: list[str], working: Path | None, icon: Path | None
) -> None:
    """A `.lnk` holding exactly these values. The thread's COM state is its own and put back."""
    initialized = ctypes.windll.ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
    if initialized not in (0, _S_OK_FALSE):
        raise OSError("the shell is not available")
    shell_link = ctypes.c_void_p()
    persist = ctypes.c_void_p()
    try:
        result = ctypes.windll.ole32.CoCreateInstance(
            _guid(_CLSID_SHELL_LINK),
            None,
            _CLSCTX_INPROC_SERVER,
            _guid(_IID_SHELL_LINK),
            ctypes.byref(shell_link),
        )
        if result != 0:
            raise OSError("the shell could not make a shortcut")
        _method(shell_link, _SET_PATH, wintypes.LPCWSTR)(shell_link, str(target))
        if arguments:
            _method(shell_link, _SET_ARGUMENTS, wintypes.LPCWSTR)(
                shell_link, subprocess.list2cmdline(arguments)
            )
        if working is not None:
            _method(shell_link, _SET_WORKING_DIRECTORY, wintypes.LPCWSTR)(shell_link, str(working))
        if icon is not None:
            _method(shell_link, _SET_ICON_LOCATION, wintypes.LPCWSTR, ctypes.c_int)(
                shell_link, str(icon), 0
            )
        _method(shell_link, _QUERY_INTERFACE, ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p))(
            shell_link, _guid(_IID_PERSIST_FILE).raw, ctypes.byref(persist)
        )
        _method(persist, _SAVE, wintypes.LPCWSTR, wintypes.BOOL)(persist, str(link), True)
    finally:
        for pointer in (persist, shell_link):
            if pointer:
                table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
                ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(table.contents[_RELEASE])(
                    pointer
                )
        ctypes.windll.ole32.CoUninitialize()


class WindowsShell:
    def recycle(self, path: Path) -> None:
        recycle(path)

    def desktop(self) -> Path:
        return desktop_folder()

    def write_shortcut(
        self,
        link: Path,
        target: Path,
        arguments: list[str],
        working: Path | None,
        icon: Path | None,
    ) -> None:
        write_shortcut(link, target, arguments, working, icon)
