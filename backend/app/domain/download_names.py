"""Turns whatever a server calls a file into one safe name inside the chosen folder. The
result is a single path segment on Windows: no separators, reserved names or trailing dots."""

import re
from urllib.parse import unquote

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{name}{i}" for name in ("COM", "LPT") for i in range(1, 10)
}
_MAX_UTF8_BYTES = 200  # Leaves room for the folder and a "(2)" within common limits.
_FILE_SEGMENT = re.compile(r"/file/([^/]+)")
_EXTENDED = re.compile(r"filename\*\s*=\s*[^']*'[^']*'([^;]+)", re.IGNORECASE)
_PLAIN = re.compile(r'filename\s*=\s*("([^"]*)"|[^;]+)', re.IGNORECASE)


def _shorten(name: str) -> str:
    """Cuts the stem and keeps the extension, without splitting a character."""
    if len(name.encode()) <= _MAX_UTF8_BYTES:
        return name
    stem, dot, extension = name.rpartition(".")
    if not dot or len(extension.encode()) > 16:
        stem, dot, extension = name, "", ""
    room = _MAX_UTF8_BYTES - len(dot.encode()) - len(extension.encode())
    return stem.encode()[:room].decode(errors="ignore").rstrip(" .") + dot + extension


def safe_file_name(raw: str | None, fallback: str) -> str:
    """`fallback` must already be safe; it is used when nothing of `raw` survives."""
    if not raw:
        return fallback
    # Only the last segment counts, whichever separator a server used.
    name = re.split(r"[/\\]", raw)[-1]
    name = _ILLEGAL.sub("_", name).strip().rstrip(" .")
    if not name.strip("._ "):
        return fallback
    if name.split(".")[0].strip().upper() in _RESERVED:
        name = f"_{name}"
    return _shorten(name)


def name_from_disposition(header: str | None) -> str | None:
    """The file name in a Content-Disposition header; the extended form wins."""
    if not header:
        return None
    extended = _EXTENDED.search(header)
    if extended:
        return unquote(extended.group(1).strip().strip('"'))
    plain = _PLAIN.search(header)
    if plain:
        return plain.group(2) if plain.group(2) is not None else plain.group(1).strip()
    return None


def name_from_path(path: str) -> str | None:
    """Download addresses carry the name in a `/file/<name>` segment, when they carry it."""
    match = _FILE_SEGMENT.search(path)
    return unquote(match.group(1)) if match else None


def numbered(name: str, number: int) -> str:
    """`a.zip` → `a (2).zip`, for keeping an existing file when a name is taken."""
    stem, dot, extension = name.rpartition(".")
    return f"{stem} ({number}).{extension}" if dot and stem else f"{name} ({number})"
