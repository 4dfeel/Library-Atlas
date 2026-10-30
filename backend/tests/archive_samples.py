"""Builds small synthetic archives byte by byte. RAR cannot be written by any tool the project
depends on, and hostile names are exactly what ordinary tools refuse to write, so these
produce real RAR 4 files (stored, uncompressed) that 7-Zip reads as it would any other."""

import struct
import zipfile
import zlib
from pathlib import Path
from typing import Any

RAR_MARKER = b"Rar!\x1a\x07\x00"
_MAIN = 0x73
_FILE = 0x74
_END = 0x7B
_LONG_BLOCK = 0x8000
_SPLIT_BEFORE = 0x01
_SPLIT_AFTER = 0x02
_VOLUME = 0x0001
_NEW_NAMING = 0x0010
_FIRST_VOLUME = 0x0100
_NEXT_VOLUME = 0x0001
_UNIX = 3
_WINDOWS = 2
_DIRECTORY_FLAG = 0x00E0


def _header(kind: int, flags: int, body: bytes) -> bytes:
    fields = struct.pack("<BHH", kind, flags, 7 + len(body)) + body
    return struct.pack("<H", zlib.crc32(fields) & 0xFFFF) + fields


def _rar_file(
    name: str,
    data: bytes,
    *,
    flags: int = 0,
    unpacked: int | None = None,
    crc: int | None = None,
    host: int = _WINDOWS,
    attributes: int = 0x20,
    name_encoding: str = "utf-8",
) -> bytes:
    encoded = name.encode(name_encoding)
    body = struct.pack(
        "<IIBIIBBHI",
        len(data),
        len(data) if unpacked is None else unpacked,
        host,
        zlib.crc32(data) if crc is None else crc,
        0x5A21_0000,
        20,
        0x30,
        len(encoded),
        attributes,
    )
    return _header(_FILE, flags | _LONG_BLOCK, body + encoded) + data


def rar(path: Path, files: dict[str, bytes], **options: Any) -> Path:
    content = RAR_MARKER + _header(_MAIN, 0, b"\0" * 6)
    for name, data in files.items():
        content += _rar_file(name, data, **options)
    content += _header(_END, 0x4000, b"")
    path.write_bytes(content)
    return path


def rar_volumes(folder: Path, stem: str, name: str, data: bytes, count: int) -> list[Path]:
    """`stem.part1.rar`, `stem.part2.rar`...: one file split across them."""
    size = len(data) // count + 1
    pieces = [data[index : index + size] for index in range(0, len(data), size)]
    assert len(pieces) == count
    paths = []
    for index, piece in enumerate(pieces):
        first, last = index == 0, index == count - 1
        main_flags = _VOLUME | _NEW_NAMING | (_FIRST_VOLUME if first else 0)
        flags = (0 if first else _SPLIT_BEFORE) | (0 if last else _SPLIT_AFTER)
        content = RAR_MARKER + _header(_MAIN, main_flags, b"\0" * 6)
        content += _rar_file(
            name, piece, flags=flags, unpacked=len(data), crc=zlib.crc32(data) if last else None
        )
        content += _header(_END, 0x4000 | (0 if last else _NEXT_VOLUME), b"")
        path = folder / f"{stem}.part{index + 1}.rar"
        path.write_bytes(content)
        paths.append(path)
    return paths


def rar_link(path: Path, name: str, target: str) -> Path:
    """A symbolic link, as a Unix tool would have stored it."""
    return rar(path, {name: target.encode()}, host=_UNIX, attributes=0o120777)


def zip_with(path: Path, files: dict[str, bytes], **options: object) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(zipfile.ZipInfo(name), data)
    return path


def zip_cp932(path: Path, name: str, data: bytes) -> Path:
    """A name in cp932 with no UTF-8 flag, as older Japanese tools wrote them."""
    temp = zip_with(path, {"placeholder.txt": data})
    raw = temp.read_bytes()
    encoded = name.encode("cp932")
    placeholder = b"placeholder.txt"
    assert len(encoded) <= len(placeholder)
    padded = encoded + b"_" * (len(placeholder) - len(encoded))
    temp.write_bytes(raw.replace(placeholder, padded))
    return temp


def zip_raw_name(path: Path, raw_name: bytes, data: bytes) -> Path:
    """Puts arbitrary bytes where the file name goes, flags untouched."""
    temp = zip_with(path, {"placeholder.txt": data})
    raw = temp.read_bytes()
    placeholder = b"placeholder.txt"
    assert len(raw_name) == len(placeholder)
    temp.write_bytes(raw.replace(placeholder, raw_name))
    return temp


def zip_link(path: Path, name: str, target: str) -> Path:
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = 0o120777 << 16
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(info, target)
    return path


def zip_lying_size(path: Path, name: str, data: bytes, declared: int) -> Path:
    """The central directory claims `declared` bytes while the entry holds more."""
    zip_with(path, {name: data})
    raw = bytearray(path.read_bytes())
    central = raw.rfind(b"PK\x01\x02")
    raw[central + 24 : central + 28] = struct.pack("<I", declared)
    local = raw.find(b"PK\x03\x04")
    raw[local + 22 : local + 26] = struct.pack("<I", declared)
    path.write_bytes(bytes(raw))
    return path
