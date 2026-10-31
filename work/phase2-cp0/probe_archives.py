"""Phase 2 CP0 probe: Japanese ZIP names and output-path containment with the standard library.

Builds synthetic archives in a fresh temp directory and removes it afterwards.
Run: python -I work/phase2-cp0/probe_archives.py
"""

import json
import struct
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path, PureWindowsPath

JP_NAME = "作品フォルダ/おまけ/読んでね.txt"


def legacy_cp932_zip(path: Path, names: list[str]) -> None:
    """Write a stored ZIP whose names are cp932 bytes without the UTF-8 flag (bit 11)."""
    local, central = b"", b""
    for name in names:
        raw = name.encode("cp932")
        data = b"synthetic"
        crc = zlib.crc32(data)
        header = struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, 0, 0, 0, crc, len(data), len(data), len(raw), 0)
        offset = len(local)
        local += header + raw + data
        central += struct.pack(
            "<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, 0, 0, 0, 0, crc, len(data), len(data), len(raw), 0, 0, 0, 0, 0, offset
        ) + raw
    end = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(names), len(names), len(central), len(local), 0)
    path.write_bytes(local + central + end)


def contained_target(root: Path, member: str) -> Path | None:
    """Return the resolved output path, or None when the member would escape `root`."""
    pure = PureWindowsPath(member.replace("/", "\\"))
    if pure.drive or pure.root or any(part == ".." for part in pure.parts):
        return None
    target = (root / Path(*pure.parts)).resolve()
    return target if target.is_relative_to(root.resolve()) else None


def main() -> None:
    result: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="atlas-cp0-") as tmp:
        tmp_path = Path(tmp)
        legacy = tmp_path / "legacy.zip"
        legacy_cp932_zip(legacy, [JP_NAME])
        with zipfile.ZipFile(legacy) as zf:
            result["default_decode_matches"] = zf.namelist() == [JP_NAME]
        with zipfile.ZipFile(legacy, metadata_encoding="cp932") as zf:
            result["cp932_decode_matches"] = zf.namelist() == [JP_NAME]

        utf8 = tmp_path / "utf8.zip"
        with zipfile.ZipFile(utf8, "w") as zf:
            zf.writestr(JP_NAME, "synthetic")
        with zipfile.ZipFile(utf8, metadata_encoding="cp932") as zf:
            result["utf8_flag_overrides_cp932"] = zf.namelist() == [JP_NAME]

        out = tmp_path / "out"
        out.mkdir()
        cases = {
            JP_NAME: True,
            "../escape.txt": False,
            "a/../../escape.txt": False,
            "C:/Windows/escape.txt": False,
            "\\\\server\\share\\x.txt": False,
            "/abs/escape.txt": False,
        }
        result["containment_cases_ok"] = all(
            (contained_target(out, name) is not None) == allowed for name, allowed in cases.items()
        )

        deep = out / ("長いフォルダ名" * 6) / ("サブフォルダ" * 40) / "ファイル.txt"
        deep.parent.mkdir(parents=True)
        deep.write_text("synthetic", encoding="utf-8")
        result["long_path_length"] = len(str(deep))
        result["long_path_write_ok"] = deep.read_text(encoding="utf-8") == "synthetic"
    json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
