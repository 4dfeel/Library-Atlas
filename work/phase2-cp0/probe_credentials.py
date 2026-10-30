"""Phase 2 CP0 probe: can this Windows user store a secret in Credential Manager and DPAPI?

Uses a fixed fake value only. Every credential written here is deleted before exit.
Run: python -I work/phase2-cp0/probe_credentials.py
"""

import ctypes
import ctypes.wintypes as wt
import json
import sys

TARGET = "LibraryAtlas/phase2-cp0-probe"
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2


class CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ("Flags", wt.DWORD),
        ("Type", wt.DWORD),
        ("TargetName", wt.LPWSTR),
        ("Comment", wt.LPWSTR),
        ("LastWritten", wt.FILETIME),
        ("CredentialBlobSize", wt.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wt.DWORD),
        ("AttributeCount", wt.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wt.LPWSTR),
        ("UserName", wt.LPWSTR),
    ]


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


advapi = ctypes.WinDLL("advapi32", use_last_error=True)
crypt = ctypes.WinDLL("crypt32", use_last_error=True)
kernel = ctypes.WinDLL("kernel32")
advapi.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), wt.DWORD]
advapi.CredReadW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
advapi.CredDeleteW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD]
advapi.CredFree.argtypes = [ctypes.c_void_p]


def cred_write(blob: bytes) -> int:
    buf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    cred = CREDENTIAL(
        Type=CRED_TYPE_GENERIC,
        TargetName=TARGET,
        CredentialBlobSize=len(blob),
        CredentialBlob=buf,
        Persist=CRED_PERSIST_LOCAL_MACHINE,
        UserName="probe",
    )
    return 0 if advapi.CredWriteW(ctypes.byref(cred), 0) else ctypes.get_last_error()


def cred_read() -> bytes | None:
    ptr = ctypes.POINTER(CREDENTIAL)()
    if not advapi.CredReadW(TARGET, CRED_TYPE_GENERIC, 0, ctypes.byref(ptr)):
        return None
    try:
        c = ptr.contents
        return bytes(c.CredentialBlob[: c.CredentialBlobSize])
    finally:
        advapi.CredFree(ptr)


def cred_delete() -> bool:
    return bool(advapi.CredDeleteW(TARGET, CRED_TYPE_GENERIC, 0))


def dpapi(data: bytes, protect: bool) -> bytes:
    src = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    blob_in = DATA_BLOB(len(data), src)
    blob_out = DATA_BLOB()
    fn = crypt.CryptProtectData if protect else crypt.CryptUnprotectData
    ok = fn(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
    if not ok:
        raise OSError(ctypes.get_last_error())
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel.LocalFree(blob_out.pbData)


def main() -> None:
    fake = b"fake-session-value-for-probe-only"
    result: dict[str, object] = {}
    result["write_small_error"] = cred_write(fake)
    result["read_back_matches"] = cred_read() == fake
    result["write_2560_error"] = cred_write(b"x" * 2560)
    result["write_2561_error"] = cred_write(b"x" * 2561)
    result["deleted"] = cred_delete()
    result["read_after_delete_is_none"] = cred_read() is None
    big = b"y" * 20000
    sealed = dpapi(big, protect=True)
    result["dpapi_roundtrip_20000_bytes"] = dpapi(sealed, protect=False) == big
    result["dpapi_ciphertext_differs"] = big not in sealed
    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
