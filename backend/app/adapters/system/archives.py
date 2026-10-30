"""Reads and unpacks archives into a folder this module is given. Nothing here decides where
results finally go, and nothing inside an archive is ever executed.

ZIP goes through the standard library, which lets every read be limited and cancelled. RAR,
7z and self-extracting files go through an installed 7-Zip, found only where its installer
registers it, never through PATH or anything named by a file. Self-extracting files are read
as data by 7-Zip; they are not run.

Encrypted archives are refused: 7-Zip takes a password only as a command-line argument, which
other programs on the machine can read.
"""

import os
import re
import stat
import subprocess
import threading
import time
import unicodedata
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

CHUNK_BYTES = 1024 * 1024
# CVE-2025-11001, -11002 and -55188: earlier versions could be led out of the output folder.
MINIMUM_7ZIP = (25, 1)
_MAGIC = {
    b"PK\x03\x04": "zip",
    b"PK\x05\x06": "zip",
    b"Rar!\x1a\x07": "rar",
    b"7z\xbc\xaf\x27\x1c": "7z",
    b"MZ": "executable",
}
_ARCHIVE_TYPES = {"zip": "zip", "rar": "rar", "rar5": "rar", "7z": "7z"}
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{name}{i}" for name in ("COM", "LPT") for i in range(1, 10)
}
_ILLEGAL = re.compile(r'[<>:"|?*\x00-\x1f]')
_PROGRESS = re.compile(rb"(\d{1,3})%")


class ArchiveProblem(Exception):
    """Why an archive cannot be unpacked. `code` is safe to store and show; nothing else is."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Stopped(Exception):
    """The caller asked to stop."""


@dataclass(frozen=True)
class Limits:
    """Generous for real works, and a hard stop for anything built to fill a disk. Size is what
    is judged, not compression ratio: a large folder of silence is a legitimate 1000:1."""

    total_bytes: int = 500 * 1024**3
    file_bytes: int = 200 * 1024**3
    files: int = 500_000
    seconds: float = 12 * 3600


@dataclass(frozen=True)
class Entry:
    path: str  # Separated by "/" and already checked by `safe_parts`.
    size: int | None
    is_dir: bool


@dataclass(frozen=True)
class Listing:
    kind: str
    entries: tuple[Entry, ...]

    @property
    def files(self) -> int:
        return sum(1 for entry in self.entries if not entry.is_dir)

    @property
    def total_bytes(self) -> int:
        return sum(entry.size or 0 for entry in self.entries if not entry.is_dir)


Progress = Callable[[int], None]
Check = Callable[[], None]


def safe_parts(raw: str) -> tuple[str, ...]:
    """The path's segments, or `unsafe_path`. Judged as Windows would read it, not as text."""
    name = raw.replace("\\", "/")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise ArchiveProblem("unsafe_path")
    parts = tuple(part for part in name.split("/") if part not in ("", "."))
    if not parts:
        raise ArchiveProblem("unsafe_path")
    for part in parts:
        if part == ".." or _ILLEGAL.search(part) or part != part.rstrip(" ."):
            raise ArchiveProblem("unsafe_path")
        if part.split(".")[0].strip().upper() in _RESERVED:
            raise ArchiveProblem("unsafe_path")
    return parts


def check_entries(entries: list[Entry], limits: Limits) -> None:
    """Refuses duplicates by the name Windows would see, and anything over the limits."""
    seen: dict[str, bool] = {}
    total = 0
    files = 0
    for entry in entries:
        folded = unicodedata.normalize("NFC", entry.path).casefold()
        if folded in seen and not (entry.is_dir and seen[folded]):
            raise ArchiveProblem("duplicate_path")
        seen[folded] = entry.is_dir
        if not entry.is_dir:
            files += 1
            size = entry.size or 0
            total += size
            if size > limits.file_bytes or total > limits.total_bytes or files > limits.files:
                raise ArchiveProblem("too_large")
    # A file standing where another entry needs a folder could not be written as listed.
    for folded in seen:
        parent = folded.rpartition("/")[0]
        while parent:
            if seen.get(parent) is False:
                raise ArchiveProblem("duplicate_path")
            parent = parent.rpartition("/")[0]


def sniff(path: Path) -> str | None:
    """What the first bytes say; the file's name has no say in it."""
    with open(path, "rb") as stream:
        start = stream.read(8)
    for magic, kind in _MAGIC.items():
        if start.startswith(magic):
            return kind
    return None


# --- ZIP ---


def _zip_names(archive: zipfile.ZipFile) -> None:
    """Without the UTF-8 flag a name's encoding is unrecorded. Japanese tools wrote cp932, and
    plain text decodes the same in it. Anything else is refused rather than guessed at."""
    for info in archive.infolist():
        if info.flag_bits & 0x800:
            continue
        try:
            info.filename.encode("cp437").decode("cp932")
        except (UnicodeDecodeError, UnicodeEncodeError):
            raise ArchiveProblem("name_encoding") from None


def _open_zip(path: Path) -> zipfile.ZipFile:
    try:
        probe = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise ArchiveProblem("damaged") from None
    except NotImplementedError:
        raise ArchiveProblem("unsupported_format") from None
    with probe:
        _zip_names(probe)
    # Now that the names are known to fit, read them in that encoding. Flagged names stay UTF-8.
    return zipfile.ZipFile(path, metadata_encoding="cp932")


def list_zip(path: Path, limits: Limits) -> Listing:
    with _open_zip(path) as archive:
        entries: list[Entry] = []
        for info in archive.infolist():
            if info.flag_bits & 0x1:
                raise ArchiveProblem("encrypted")
            if info.compress_type not in (
                zipfile.ZIP_STORED,
                zipfile.ZIP_DEFLATED,
                zipfile.ZIP_BZIP2,
                zipfile.ZIP_LZMA,
            ):
                raise ArchiveProblem("unsupported_format")
            # A link is marked only in the Unix attributes kept alongside the entry.
            if stat.S_ISLNK(info.external_attr >> 16) or info.external_attr & 0x400:
                raise ArchiveProblem("special_entry")
            parts = safe_parts(info.filename)
            entries.append(Entry("/".join(parts), info.file_size, info.is_dir()))
    check_entries(entries, limits)
    return Listing("zip", tuple(entries))


def extract_zip(path: Path, output: Path, limits: Limits, progress: Progress, check: Check) -> None:
    """Counts what actually comes out: an entry may declare one size and hold another."""
    began = time.monotonic()
    done = 0
    with _open_zip(path) as archive:
        for info in archive.infolist():
            target = output.joinpath(*safe_parts(info.filename))
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            try:
                with archive.open(info) as source, open(target, "xb") as sink:
                    while chunk := source.read(CHUNK_BYTES):
                        check()
                        written += len(chunk)
                        done += len(chunk)
                        if (
                            written > limits.file_bytes
                            or done > limits.total_bytes
                            or time.monotonic() - began > limits.seconds
                        ):
                            raise ArchiveProblem("too_large")
                        sink.write(chunk)
                        progress(done)
            except (zipfile.BadZipFile, EOFError):
                raise ArchiveProblem("damaged") from None
            except FileExistsError:
                raise ArchiveProblem("duplicate_path") from None
            except NotImplementedError:
                raise ArchiveProblem("unsupported_format") from None
            except OSError as error:
                if "CRC" in str(error) or "Bad" in str(error):
                    raise ArchiveProblem("damaged") from None
                raise


# --- 7-Zip ---


def _registered_folders() -> Iterator[Path]:
    """Where the 7-Zip installer says it went, then the default install folders."""
    try:
        import winreg
    except ImportError:
        return
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, r"SOFTWARE\7-Zip") as key:
                for name in ("Path64", "Path"):
                    try:
                        value, _kind = winreg.QueryValueEx(key, name)
                    except OSError:
                        continue
                    if value:
                        yield Path(str(value))
        except OSError:
            continue
    for variable in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        root = os.environ.get(variable)
        if root:
            yield Path(root) / "7-Zip"


def _hidden() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _version(executable: Path) -> tuple[int, int] | None:
    try:
        result = subprocess.run(  # noqa: S603 - verified program, argument list
            [str(executable), "i"],
            capture_output=True,
            timeout=15,
            stdin=subprocess.DEVNULL,
            creationflags=_hidden(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(rb"7-Zip (?:\(\w\) )?(\d+)\.(\d+)", result.stdout)
    return (int(match.group(1)), int(match.group(2))) if match else None


class SevenZip:
    """One verified 7z.exe. Arguments are always a list, and `--` ends the switches, so a file
    name can never be read as an option."""

    def __init__(self, executable: Path) -> None:
        self.executable = executable

    def _list_output(self, path: Path) -> bytes:
        # -p- answers any password question with "no" instead of waiting for one.
        result = subprocess.run(  # noqa: S603 - verified program, argument list
            [str(self.executable), "l", "-slt", "-p-", "-sccUTF-8", "-scsUTF-8", "--", str(path)],
            capture_output=True,
            timeout=300,
            stdin=subprocess.DEVNULL,
            creationflags=_hidden(),
        )
        combined = result.stdout + b"\n" + result.stderr
        if result.returncode != 0:
            raise ArchiveProblem(_failure_code(combined))
        return result.stdout

    def kind(self, path: Path) -> str | None:
        """The archive format, or None when 7-Zip reads it as something else (a plain program
        is an archive of sections to 7-Zip, and is not one here)."""
        try:
            output = self._list_output(path)
        except ArchiveProblem as problem:
            if problem.code in ("encrypted", "missing_parts"):
                raise
            return None
        match = re.search(rb"^Type = (\S+)", output, re.MULTILINE)
        return (
            _ARCHIVE_TYPES.get(match.group(1).decode("ascii", "replace").lower()) if match else None
        )

    def list(self, path: Path, limits: Limits) -> Listing:
        output = self._list_output(path)
        match = re.search(rb"^Type = (\S+)", output, re.MULTILINE)
        kind = (
            _ARCHIVE_TYPES.get(match.group(1).decode("ascii", "replace").lower()) if match else None
        )
        if kind is None:
            raise ArchiveProblem("unsupported_format")
        entries: list[Entry] = []
        body = output.split(b"----------\n" if b"\r\n" not in output else b"----------\r\n", 1)
        for block in re.split(rb"\r?\n\r?\n", body[-1]):
            fields: dict[bytes, bytes] = {}
            for line in block.splitlines():
                name, separator, value = line.partition(b" = ")
                if separator:
                    fields[name.strip()] = value
            if b"Path" not in fields:
                continue
            if fields.get(b"Encrypted") == b"+":
                raise ArchiveProblem("encrypted")
            attributes = fields.get(b"Attributes", b"")
            if (
                fields.get(b"Symbolic Link")
                or fields.get(b"Hard Link")
                or fields.get(b"Alternate Stream") == b"+"
                or _attribute_is_link(attributes)
            ):
                raise ArchiveProblem("special_entry")
            is_dir = fields.get(b"Folder") == b"+" or attributes.startswith(b"D")
            parts = safe_parts(fields[b"Path"].decode("utf-8", "replace"))
            size = fields.get(b"Size", b"")
            entries.append(Entry("/".join(parts), int(size) if size.isdigit() else None, is_dir))
        check_entries(entries, limits)
        return Listing(kind, tuple(entries))

    def extract(
        self, path: Path, output: Path, limits: Limits, progress: Progress, check: Check
    ) -> None:
        """Only this one process is ever stopped, through its own handle. What it writes is
        measured while it runs, because a listing can lie."""
        output.mkdir(parents=True, exist_ok=True)
        process = subprocess.Popen(  # noqa: S603 - verified program, argument list
            [
                str(self.executable),
                "x",
                "-p-",
                "-y",
                "-aou",  # Never replaces; a rename shows up as an extra file in the final check.
                "-sns-",
                "-bsp1",
                "-bso0",
                "-sccUTF-8",
                f"-o{output}",
                "--",
                str(path),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=_hidden(),
        )
        errors: list[bytes] = []
        percent = [0]

        def read_progress() -> None:
            assert process.stdout is not None
            while chunk := process.stdout.read(256):
                matches = _PROGRESS.findall(chunk)
                if matches:
                    percent[0] = min(100, int(matches[-1]))

        def read_errors() -> None:
            assert process.stderr is not None
            errors.append(process.stderr.read())

        readers = [
            threading.Thread(target=read_progress, daemon=True),
            threading.Thread(target=read_errors, daemon=True),
        ]
        for reader in readers:
            reader.start()
        began = time.monotonic()
        try:
            while process.poll() is None:
                check()
                if time.monotonic() - began > limits.seconds:
                    raise ArchiveProblem("too_large")
                size, files = _measure(output)
                if size > limits.total_bytes or files > limits.files:
                    raise ArchiveProblem("too_large")
                progress(size)
                time.sleep(0.2)
        except BaseException:
            process.kill()
            process.wait()
            raise
        finally:
            for reader in readers:
                reader.join(timeout=5)
        if process.returncode != 0:
            raise ArchiveProblem(_failure_code(b"".join(errors)))


def _attribute_is_link(attributes: bytes) -> bool:
    """7-Zip prints Windows attributes first and, for Unix-made archives, the mode after them."""
    text = attributes.decode("ascii", "replace")
    return bool(re.search(r"(^|\s)l[rwx-]{9}", text)) or "L" in text.split(" ")[0]


def _failure_code(output: bytes) -> str:
    text = output.lower()
    if b"encrypted" in text or b"wrong password" in text:
        return "encrypted"
    if b"missing volume" in text or b"unexpected end" in text or b"unavailable" in text:
        return "missing_parts"
    if b"not enough space" in text or b"there is not enough" in text:
        return "disk_full"
    if b"cannot open the file as" in text or b"not archive" in text or b"crc" in text:
        return "damaged"
    if b"data error" in text or b"headers error" in text:
        return "damaged"
    return "extract_failed"


def _measure(folder: Path) -> tuple[int, int]:
    """Bytes and files under a folder, without following links."""
    size = 0
    files = 0
    stack = [str(folder)]
    while stack:
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    else:
                        files += 1
                        try:
                            size += entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            continue
        except OSError:
            continue
    return size, files


def find_seven_zip() -> SevenZip | None:
    """None when no acceptable 7-Zip is installed: too old counts as absent."""
    for folder in _registered_folders():
        executable = folder / "7z.exe"
        if executable.is_file():
            version = _version(executable)
            if version is not None and version >= MINIMUM_7ZIP:
                return SevenZip(executable)
    return None


def verify_output(output: Path, listing: Listing) -> None:
    """A tool's success is not enough: the folder must hold what was listed and nothing else,
    and nothing in it may lead elsewhere."""
    expected = {
        unicodedata.normalize("NFC", entry.path).casefold(): entry for entry in listing.entries
    }
    found_files = 0
    stack = [(str(output), "")]
    while stack:
        folder, prefix = stack.pop()
        with os.scandir(folder) as entries:
            for item in entries:
                relative = f"{prefix}{item.name}"
                key = unicodedata.normalize("NFC", relative).casefold()
                info = item.stat(follow_symlinks=False)
                reparse = getattr(info, "st_file_attributes", 0) & getattr(
                    stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
                )
                if reparse or item.is_symlink():
                    raise ArchiveProblem("special_entry")
                if item.is_dir(follow_symlinks=False):
                    stack.append((item.path, f"{relative}/"))
                    continue
                entry = expected.get(key)
                if entry is None or entry.is_dir:
                    raise ArchiveProblem("output_mismatch")
                if entry.size is not None and entry.size != info.st_size:
                    raise ArchiveProblem("output_mismatch")
                found_files += 1
    if found_files != listing.files:
        raise ArchiveProblem("output_mismatch")
