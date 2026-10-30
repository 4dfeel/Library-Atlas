"""Turns whatever a server calls a file into one safe name inside the chosen folder. The
result is a single path segment on Windows: no separators, reserved names or trailing dots."""

import re
from urllib.parse import unquote

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{name}{i}" for name in ("COM", "LPT") for i in range(1, 10)
}
_MAX_UTF8_BYTES = 200  # Leaves room for the folder and a "(2)" within common limits.
_MAX_FOLDER_BYTES = 120  # Works unpack many levels deep: titles leave them room.
_MAX_MAKER_BYTES = 80
_KIND_FOLDERS = {
    "game": "Game",
    "audio": "Audio",
    "video": "Movie",
    "image": "Illust",
    "other": "Other",
}
_COMIC_CODES = {"MNG", "SCM", "WBT", "VCM"}
_UNKNOWN_MAKER = "未知制作方"
_FILE_SEGMENT = re.compile(r"/file/([^/]+)")
_EXTENDED = re.compile(r"filename\*\s*=\s*[^']*'[^']*'([^;]+)", re.IGNORECASE)
_PLAIN = re.compile(r'filename\s*=\s*("([^"]*)"|[^;]+)', re.IGNORECASE)


def _shorten(name: str, limit: int = _MAX_UTF8_BYTES) -> str:
    """Cuts the stem and keeps the extension, without splitting a character."""
    if len(name.encode()) <= limit:
        return name
    stem, dot, extension = name.rpartition(".")
    if not dot or len(extension.encode()) > 16:
        stem, dot, extension = name, "", ""
    room = limit - len(dot.encode()) - len(extension.encode())
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


def safe_folder_name(raw: str | None, fallback: str, limit: int = _MAX_FOLDER_BYTES) -> str:
    """A work's title or maker as one folder name. Unlike a server's file name, a slash here is
    part of the name, not a path to discard the front of."""
    name = _ILLEGAL.sub("_", raw or "").strip().rstrip(" .")
    if not name.strip("._ "):
        return fallback
    if name.split(".")[0].strip().upper() in _RESERVED:
        name = f"_{name}"
    cut = name.encode()[:limit].decode(errors="ignore").strip().rstrip(" .")
    return cut or fallback


def work_folder(
    kind: str, raw_kind: str | None, maker: str | None, title: str, fallback: str
) -> tuple[str, str, str]:
    """`<type>/<maker>/<title>`, the layout the user keeps their works in. Names are for reading:
    what a folder belongs to is on record in the database, so two works may share a title."""
    folder = _KIND_FOLDERS.get(kind, "Other")
    if kind == "image" and raw_kind in _COMIC_CODES:
        folder = "Comic"
    return (
        folder,
        safe_folder_name(maker, _UNKNOWN_MAKER, _MAX_MAKER_BYTES),
        safe_folder_name(title, fallback),
    )


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
