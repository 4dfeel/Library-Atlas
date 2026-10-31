"""Knowing when a game has really ended, launchers included.

A Windows job follows a process and everything it starts, so a launcher that hands over and quits
does not end the session, while the last process leaving it does. The job has a name so that Atlas
can find it again after a restart, and closing Atlas never closes the game. It cannot follow what
asks Windows to run it elevated, or what is handed to an already-running program.
"""

import ctypes
import subprocess
from ctypes import wintypes
from typing import Protocol

_JOB_QUERY = 0x0004
_BASIC_ACCOUNTING = 1


class _Accounting(ctypes.Structure):
    _fields_ = (
        ("TotalUserTime", ctypes.c_longlong),
        ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong),
        ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    )


def _kernel32() -> ctypes.WinDLL:
    library = ctypes.WinDLL("kernel32", use_last_error=True)
    library.CreateJobObjectW.restype = wintypes.HANDLE
    library.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
    library.OpenJobObjectW.restype = wintypes.HANDLE
    library.OpenJobObjectW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    library.AssignProcessToJobObject.restype = wintypes.BOOL
    library.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    library.QueryInformationJobObject.restype = wintypes.BOOL
    library.QueryInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.LPDWORD,
    )
    library.CloseHandle.argtypes = (wintypes.HANDLE,)
    return library


class RunningGame(Protocol):
    name: str | None

    def running(self) -> bool: ...
    def close(self) -> None: ...


class ProcessWatch:
    """Falls back to the started process alone if a job cannot be had, and says so by its name."""

    def __init__(
        self, handle: int | None, process: subprocess.Popen[bytes] | None, name: str | None
    ):
        self._handle = handle
        self._process = process
        self.name = name
        self._kernel = _kernel32()

    @classmethod
    def follow(cls, process: subprocess.Popen[bytes], name: str) -> ProcessWatch:
        kernel = _kernel32()
        handle = kernel.CreateJobObjectW(None, f"Local\\{name}")
        if handle and kernel.AssignProcessToJobObject(handle, int(process._handle)):  # type: ignore[attr-defined]
            return cls(handle, process, name)
        if handle:
            kernel.CloseHandle(handle)
        return cls(None, process, None)

    @classmethod
    def reopen(cls, name: str) -> ProcessWatch | None:
        """After a restart. None means it is gone: the game ended while Atlas was away."""
        handle = _kernel32().OpenJobObjectW(_JOB_QUERY, False, f"Local\\{name}")
        return cls(handle, None, name) if handle else None

    def running(self) -> bool:
        if self._handle:
            info = _Accounting()
            if self._kernel.QueryInformationJobObject(
                self._handle, _BASIC_ACCOUNTING, ctypes.byref(info), ctypes.sizeof(info), None
            ):
                return bool(info.ActiveProcesses > 0)
        return self._process is not None and self._process.poll() is None

    def close(self) -> None:
        if self._handle:
            self._kernel.CloseHandle(self._handle)
            self._handle = None
