"""Boundary for platform secrets. Only this module talks to the credential store.

Checkpoint 1 has no real secrets: nothing calls this outside its tests, and session
saving, refresh and chunking belong to later checkpoints. Failures raise rather than
fall back to any plaintext location.
"""

import ctypes
import sys
from ctypes import wintypes
from typing import Protocol

NAMESPACE = "LibraryAtlas/"
MAX_BLOB_BYTES = 2560  # Measured limit of CredWriteW; see PHASE2_CAPABILITY_MATRIX E14.
_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_ERROR_NOT_FOUND = 1168


class CredentialStoreError(Exception):
    """The store is unavailable or refused the operation. Holds no secret values."""


class CredentialTooLarge(CredentialStoreError):
    pass


class CredentialStore(Protocol):
    def read(self, name: str) -> bytes | None: ...
    def write(self, name: str, secret: bytes) -> None: ...
    def delete(self, name: str) -> None: ...


class _FileTime(ctypes.Structure):
    _fields_ = (("low", wintypes.DWORD), ("high", wintypes.DWORD))


class _Credential(ctypes.Structure):
    _fields_ = (
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", _FileTime),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    )


class WindowsCredentialStore:
    """Generic credentials under one namespace, so nothing else can be touched."""

    def __init__(self, namespace: str = NAMESPACE) -> None:
        if sys.platform != "win32":
            raise CredentialStoreError("Windows 凭据存储不可用。")
        if not namespace.startswith(NAMESPACE):
            raise CredentialStoreError("凭据命名空间无效。")
        self._namespace = namespace
        self._api = ctypes.WinDLL("advapi32", use_last_error=True)
        self._api.CredReadW.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_Credential)),
        )
        self._api.CredWriteW.argtypes = (ctypes.POINTER(_Credential), wintypes.DWORD)
        self._api.CredDeleteW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD)
        self._api.CredFree.argtypes = (ctypes.c_void_p,)

    def _target(self, name: str) -> str:
        if not name or "\0" in name:
            raise CredentialStoreError("凭据名称无效。")
        return f"{self._namespace}{name}"

    def read(self, name: str) -> bytes | None:
        pointer = ctypes.POINTER(_Credential)()
        if not self._api.CredReadW(
            self._target(name), _CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)
        ):
            if ctypes.get_last_error() == _ERROR_NOT_FOUND:
                return None
            raise CredentialStoreError("无法读取 Windows 凭据存储。")
        try:
            credential = pointer.contents
            return ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
        finally:
            self._api.CredFree(pointer)

    def write(self, name: str, secret: bytes) -> None:
        if len(secret) > MAX_BLOB_BYTES:
            raise CredentialTooLarge("凭据超过 Windows 单条上限。")
        blob = (ctypes.c_ubyte * len(secret)).from_buffer_copy(secret)
        credential = _Credential(
            Type=_CRED_TYPE_GENERIC,
            TargetName=self._target(name),
            CredentialBlobSize=len(secret),
            CredentialBlob=blob,
            Persist=_CRED_PERSIST_LOCAL_MACHINE,
        )
        if not self._api.CredWriteW(ctypes.byref(credential), 0):
            raise CredentialStoreError("无法写入 Windows 凭据存储。")

    def delete(self, name: str) -> None:
        if not self._api.CredDeleteW(self._target(name), _CRED_TYPE_GENERIC, 0):
            if ctypes.get_last_error() != _ERROR_NOT_FOUND:
                raise CredentialStoreError("无法删除 Windows 凭据。")
