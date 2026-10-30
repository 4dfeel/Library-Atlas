"""The archive readers against real files and the real 7-Zip. Every hostile case checks that a
sentinel outside the output folder is untouched, not merely that an error was raised."""

import subprocess
import time
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.adapters.system.archives import (
    MINIMUM_7ZIP,
    ArchiveProblem,
    Entry,
    Limits,
    Listing,
    SevenZip,
    Stopped,
    check_entries,
    extract_zip,
    find_seven_zip,
    list_zip,
    safe_parts,
    sniff,
    verify_output,
)
from tests import archive_samples as samples

LIMITS = Limits()


def ignore(_value: int) -> None:
    return None


def carry_on() -> None:
    return None


@pytest.fixture
def seven() -> SevenZip:
    tool = find_seven_zip()
    if tool is None:
        pytest.skip(f"needs 7-Zip {MINIMUM_7ZIP} or newer installed")
    return tool


@pytest.fixture
def box(tmp_path: Path) -> Iterator[tuple[Path, Path, Path]]:
    """Output folder, a place for archives, and a sentinel just outside the output."""
    root = tmp_path / "解压 テスト"
    output = root / "output"
    output.mkdir(parents=True)
    sources = root / "sources"
    sources.mkdir()
    sentinel = root / "sentinel.txt"
    sentinel.write_text("untouched", encoding="utf-8")
    yield output, sources, sentinel
    assert sentinel.read_text(encoding="utf-8") == "untouched"
    assert sorted(path.name for path in root.iterdir()) == ["output", "sentinel.txt", "sources"]


def build_with_tool(
    seven: SevenZip, archive: Path, files: dict[str, bytes], *switches: str
) -> Path:
    source = archive.parent / f"{archive.stem}-content"
    for name, data in files.items():
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    subprocess.run(
        [str(seven.executable), "a", "-bso0", "-bsp0", *switches, str(archive), "."],
        cwd=source,
        check=True,
        stdin=subprocess.DEVNULL,
    )
    return archive


# --- what a path means ---


@pytest.mark.parametrize(
    "name",
    [
        "../evil.txt",
        "a/../../evil.txt",
        "..\\evil.txt",
        "a\\..\\..\\evil.txt",
        "/etc/passwd",
        "\\Windows\\evil.txt",
        "C:\\Windows\\evil.txt",
        "C:evil.txt",
        "\\\\server\\share\\evil.txt",
        "file.txt:stream",
        "file.txt::$DATA",
        "CON",
        "dir/NUL.txt",
        "com1.zip",
        "LPT9",
        "trailing.",
        "trailing ",
        "dir./file.txt",
        "a|b.txt",
        "a\x01b.txt",
        "",
        "./.",
    ],
)
def test_paths_that_could_leave_or_mislead_are_refused(name: str) -> None:
    with pytest.raises(ArchiveProblem) as problem:
        safe_parts(name)
    assert problem.value.code == "unsafe_path"


@pytest.mark.parametrize(
    ("name", "parts"),
    [
        ("作品/音声/01 はじめに.wav", ("作品", "音声", "01 はじめに.wav")),
        ("a\\b.txt", ("a", "b.txt")),
        ("./a//b.txt", ("a", "b.txt")),
        ("dir/", ("dir",)),
        ("..hidden/.file", ("..hidden", ".file")),
        ("console.txt", ("console.txt",)),
        ("a.b.c", ("a.b.c",)),
    ],
)
def test_ordinary_names_pass(name: str, parts: tuple[str, ...]) -> None:
    assert safe_parts(name) == parts


@pytest.mark.parametrize(
    "paths",
    [
        ["a.txt", "a.txt"],
        ["A.TXT", "a.txt"],
        ["caf\u00e9.txt", "cafe\u0301.txt"],
        ["ß/x.txt", "ß/x.txt"],
    ],
)
def test_names_windows_would_merge_are_refused(paths: list[str]) -> None:
    entries = [Entry(path, 1, False) for path in paths]
    with pytest.raises(ArchiveProblem) as problem:
        check_entries(entries, LIMITS)
    assert problem.value.code == "duplicate_path"


def test_a_file_where_a_folder_is_needed_is_refused() -> None:
    entries = [Entry("a", 1, False), Entry("a/b.txt", 1, False)]
    with pytest.raises(ArchiveProblem):
        check_entries(entries, LIMITS)


def test_a_folder_listed_twice_is_harmless() -> None:
    check_entries([Entry("a", None, True), Entry("a", None, True)], LIMITS)


@pytest.mark.parametrize(
    "limits",
    [Limits(total_bytes=10), Limits(file_bytes=10), Limits(files=1)],
)
def test_limits_are_enforced_on_the_listing(limits: Limits) -> None:
    entries = [Entry("a.bin", 6, False), Entry("b.bin", 6, False)]
    with pytest.raises(ArchiveProblem) as problem:
        check_entries(entries, limits if limits.file_bytes != 10 else Limits(file_bytes=5))
    assert problem.value.code == "too_large"


def test_identity_comes_from_content_not_the_name(tmp_path: Path) -> None:
    disguised = samples.zip_with(tmp_path / "picture.png", {"a.txt": b"x"})
    assert sniff(disguised) == "zip"
    plain = tmp_path / "archive.zip"
    plain.write_bytes(b"not an archive at all")
    assert sniff(plain) is None
    assert sniff(samples.rar(tmp_path / "a.bin", {"a.txt": b"x"})) == "rar"


# --- ZIP ---


def test_zip_unpacks_with_unicode_names_and_folders(box: tuple[Path, Path, Path]) -> None:
    output, sources, _sentinel = box
    archive = sources / "a.zip"
    files = {"音声/01 はじめに.wav": b"a" * 1000, "説明 書.txt": b"b", "empty/": b""}
    samples.zip_with(archive, files)
    listing = list_zip(archive, LIMITS)
    assert listing.kind == "zip"
    assert listing.files == 2
    assert listing.total_bytes == 1001
    seen: list[int] = []
    extract_zip(archive, output, LIMITS, seen.append, carry_on)
    assert (output / "音声" / "01 はじめに.wav").read_bytes() == b"a" * 1000
    assert (output / "empty").is_dir()
    assert seen[-1] == 1001
    verify_output(output, listing)


def test_zip_reads_unmarked_japanese_names_as_cp932(box: tuple[Path, Path, Path]) -> None:
    output, sources, _sentinel = box
    archive = samples.zip_cp932(sources / "a.zip", "音声.wav", b"data")
    listing = list_zip(archive, LIMITS)
    assert listing.entries[0].path.startswith("音声")
    extract_zip(archive, output, LIMITS, ignore, carry_on)
    verify_output(output, listing)
    assert [path.name for path in output.iterdir()] == [listing.entries[0].path]


def test_zip_names_in_an_unknown_encoding_are_refused_not_guessed(
    box: tuple[Path, Path, Path],
) -> None:
    _output, sources, _sentinel = box
    # 0x81 then 0x20 is not valid cp932.
    archive = samples.zip_raw_name(sources / "a.zip", b"\x81\x20bad_name1.txt", b"x")
    with pytest.raises(ArchiveProblem) as problem:
        list_zip(archive, LIMITS)
    assert problem.value.code == "name_encoding"


@pytest.mark.parametrize(
    "name", ["../sentinel.txt", "..\\sentinel.txt", "a/../../sentinel.txt", "C:\\evil.txt"]
)
def test_zip_cannot_write_outside(box: tuple[Path, Path, Path], name: str) -> None:
    output, sources, _sentinel = box
    archive = samples.zip_with(sources / "a.zip", {name: b"overwritten"})
    with pytest.raises(ArchiveProblem):
        list_zip(archive, LIMITS)
    with pytest.raises(ArchiveProblem):
        extract_zip(archive, output, LIMITS, ignore, carry_on)


def test_zip_refuses_links_and_encryption(box: tuple[Path, Path, Path]) -> None:
    _output, sources, _sentinel = box
    linked = samples.zip_link(sources / "link.zip", "link", "../sentinel.txt")
    with pytest.raises(ArchiveProblem) as problem:
        list_zip(linked, LIMITS)
    assert problem.value.code == "special_entry"
    encrypted = samples.zip_with(sources / "enc.zip", {"a.txt": b"x"})
    raw = bytearray(encrypted.read_bytes())
    central = raw.rfind(b"PK\x01\x02")
    raw[central + 8] |= 0x1
    encrypted.write_bytes(bytes(raw))
    with pytest.raises(ArchiveProblem) as problem:
        list_zip(encrypted, LIMITS)
    assert problem.value.code == "encrypted"


def test_zip_that_lies_about_its_size_is_stopped_while_writing(
    box: tuple[Path, Path, Path],
) -> None:
    output, sources, _sentinel = box
    archive = samples.zip_lying_size(sources / "a.zip", "a.bin", b"z" * 500_000, 10)
    assert list_zip(archive, LIMITS).total_bytes == 10
    with pytest.raises(ArchiveProblem):
        extract_zip(archive, output, Limits(total_bytes=1000), ignore, carry_on)
    assert sum(path.stat().st_size for path in output.rglob("*") if path.is_file()) <= 1_100_000


def test_zip_damage_is_reported(box: tuple[Path, Path, Path]) -> None:
    output, sources, _sentinel = box
    damaged = samples.zip_with(sources / "a.zip", {"a.bin": b"content" * 1000})
    raw = bytearray(damaged.read_bytes())
    raw[60] ^= 0xFF
    damaged.write_bytes(bytes(raw))
    with pytest.raises(ArchiveProblem) as problem:
        extract_zip(damaged, output, LIMITS, ignore, carry_on)
    assert problem.value.code == "damaged"
    truncated = sources / "t.zip"
    truncated.write_bytes(damaged.read_bytes()[:40])
    with pytest.raises(ArchiveProblem) as problem:
        list_zip(truncated, LIMITS)
    assert problem.value.code == "damaged"


def test_zip_stops_when_told(box: tuple[Path, Path, Path]) -> None:
    output, sources, _sentinel = box
    archive = sources / "a.zip"
    with zipfile.ZipFile(archive, "w") as stored:
        stored.writestr("a.bin", b"x" * (5 * 1024 * 1024))

    def stop() -> None:
        raise Stopped

    with pytest.raises(Stopped):
        extract_zip(archive, output, LIMITS, ignore, stop)


# --- 7-Zip ---


def test_seven_zip_is_found_only_where_it_is_registered(
    seven: SevenZip, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = tmp_path / "7z.exe"
    fake.write_bytes(b"not a program")
    monkeypatch.setenv("PATH", str(tmp_path))
    found = find_seven_zip()
    assert found is not None
    assert found.executable != fake


def test_too_old_a_version_counts_as_missing(
    monkeypatch: pytest.MonkeyPatch, seven: SevenZip
) -> None:
    from app.adapters.system import archives

    monkeypatch.setattr(archives, "_version", lambda _path: (24, 9))
    assert find_seven_zip() is None


def test_rar_unpacks(seven: SevenZip, box: tuple[Path, Path, Path]) -> None:
    output, sources, _sentinel = box
    archive = samples.rar(sources / "a.rar", {"dir\\a.txt": b"hello", "b.bin": b"x" * 5000})
    assert seven.kind(archive) == "rar"
    listing = seven.list(archive, LIMITS)
    assert listing.kind == "rar"
    assert listing.files == 2
    assert listing.total_bytes == 5005
    seven.extract(archive, output, LIMITS, ignore, carry_on)
    assert (output / "dir" / "a.txt").read_bytes() == b"hello"
    verify_output(output, listing)


def test_split_rar_needs_every_part(seven: SevenZip, box: tuple[Path, Path, Path]) -> None:
    output, sources, _sentinel = box
    data = bytes(range(256)) * 400
    parts = samples.rar_volumes(sources, "work", "movie.bin", data, 3)
    listing = seven.list(parts[0], LIMITS)
    assert listing.files == 1
    seven.extract(parts[0], output, LIMITS, ignore, carry_on)
    assert (output / "movie.bin").read_bytes() == data
    verify_output(output, listing)

    for path in output.iterdir():
        path.unlink()
    parts[2].unlink()
    with pytest.raises(ArchiveProblem) as problem:
        seven.extract(parts[0], output, LIMITS, ignore, carry_on)
    assert problem.value.code in ("missing_parts", "damaged")


@pytest.mark.parametrize("name", ["..\\sentinel.txt", "a\\..\\..\\sentinel.txt"])
def test_rar_cannot_write_outside(seven: SevenZip, box: tuple[Path, Path, Path], name: str) -> None:
    _output, sources, _sentinel = box
    archive = samples.rar(sources / "a.rar", {name: b"overwritten"})
    with pytest.raises(ArchiveProblem) as problem:
        seven.list(archive, LIMITS)
    assert problem.value.code == "unsafe_path"


def test_a_rar_link_cannot_become_a_link_on_disk(
    seven: SevenZip, box: tuple[Path, Path, Path]
) -> None:
    """7-Zip does not report a link in a RAR 4 listing, so the listing alone cannot catch it.
    What is actually written is what counts: no link may exist, and the target stays intact."""
    output, sources, sentinel = box
    archive = samples.rar_link(sources / "a.rar", "link", str(sentinel))
    try:
        listing = seven.list(archive, LIMITS)
        seven.extract(archive, output, LIMITS, ignore, carry_on)
        verify_output(output, listing)
    except ArchiveProblem:
        return  # Refused outright is fine too.
    written = output / "link"
    assert not written.is_symlink()
    assert written.read_bytes() == str(sentinel).encode()


def test_7z_unpacks_and_encrypted_is_refused(seven: SevenZip, box: tuple[Path, Path, Path]) -> None:
    output, sources, _sentinel = box
    archive = build_with_tool(seven, sources / "a.7z", {"日本語/a.txt": b"hello"})
    assert seven.kind(archive) == "7z"
    listing = seven.list(archive, LIMITS)
    seven.extract(archive, output, LIMITS, ignore, carry_on)
    assert (output / "日本語" / "a.txt").read_bytes() == b"hello"
    verify_output(output, listing)

    locked = build_with_tool(seven, sources / "b.7z", {"a.txt": b"x"}, "-pSENTINEL", "-mhe=on")
    with pytest.raises(ArchiveProblem) as problem:
        seven.list(locked, LIMITS)
    assert problem.value.code == "encrypted"
    locked = build_with_tool(seven, sources / "c.7z", {"a.txt": b"x"}, "-pSENTINEL")
    with pytest.raises(ArchiveProblem) as problem:
        seven.list(locked, LIMITS)
    assert problem.value.code == "encrypted"


def test_self_extracting_files_are_read_not_run(
    seven: SevenZip, box: tuple[Path, Path, Path]
) -> None:
    output, sources, _sentinel = box
    canary = sources / "ran.txt"
    archive = build_with_tool(seven, sources / "a.exe", {"a.txt": b"hello"}, "-sfx")
    assert sniff(archive) == "executable"
    assert seven.kind(archive) == "7z"
    listing = seven.list(archive, LIMITS)
    seven.extract(archive, output, LIMITS, ignore, carry_on)
    assert (output / "a.txt").read_bytes() == b"hello"
    verify_output(output, listing)
    assert not canary.exists()


def test_a_plain_program_is_not_an_archive(seven: SevenZip) -> None:
    # 7-Zip reads any program as an archive of its sections. To Atlas it is just a file.
    assert seven.kind(seven.executable) is None


def test_a_file_named_like_a_switch_stays_a_file(
    seven: SevenZip, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    archive = samples.rar(tmp_path / "-sfx.rar", {"a.txt": b"hello"})
    listing = seven.list(Path(archive.name), LIMITS)
    assert listing.files == 1


def test_seven_zip_is_stopped_when_told_and_leaves_no_process(
    seven: SevenZip, box: tuple[Path, Path, Path]
) -> None:
    output, sources, _sentinel = box
    archive = build_with_tool(
        seven, sources / "big.7z", {f"{i}.bin": bytes(range(256)) * 40_000 for i in range(30)}
    )
    began = time.monotonic()

    def stop() -> None:
        if time.monotonic() - began > 0.01:
            raise Stopped

    with pytest.raises(Stopped):
        seven.extract(archive, output, LIMITS, ignore, stop)
    # The handle was waited on, so the folder can be removed at once.
    assert time.monotonic() - began < 5
    for path in output.rglob("*"):
        if path.is_file():
            path.unlink()


def test_seven_zip_output_is_measured_while_running(
    seven: SevenZip, box: tuple[Path, Path, Path]
) -> None:
    output, sources, _sentinel = box
    archive = build_with_tool(
        seven, sources / "big.7z", {f"{i}.bin": bytes(range(256)) * 40_000 for i in range(30)}
    )
    with pytest.raises(ArchiveProblem) as problem:
        seven.extract(archive, output, Limits(total_bytes=1000), ignore, carry_on)
    assert problem.value.code == "too_large"


def test_corrupt_data_is_reported(seven: SevenZip, box: tuple[Path, Path, Path]) -> None:
    output, sources, _sentinel = box
    archive = samples.rar(sources / "a.rar", {"a.bin": b"content" * 100})
    raw = bytearray(archive.read_bytes())
    raw[-50] ^= 0xFF
    archive.write_bytes(bytes(raw))
    with pytest.raises(ArchiveProblem) as problem:
        seven.extract(archive, output, LIMITS, ignore, carry_on)
    assert problem.value.code in ("damaged", "extract_failed")


# --- the final check ---


def _listing(*files: tuple[str, int]) -> Listing:
    return Listing("zip", tuple(Entry(name, size, False) for name, size in files))


def test_verify_accepts_what_was_listed(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"abc")
    verify_output(tmp_path, _listing(("a.txt", 3)))


@pytest.mark.parametrize(
    "listing",
    [
        _listing(("a.txt", 4)),  # A different size.
        _listing(("a.txt", 3), ("b.txt", 1)),  # Something missing.
        _listing(),  # Something extra.
    ],
)
def test_verify_refuses_any_difference(tmp_path: Path, listing: Listing) -> None:
    (tmp_path / "a.txt").write_bytes(b"abc")
    with pytest.raises(ArchiveProblem) as problem:
        verify_output(tmp_path, listing)
    assert problem.value.code == "output_mismatch"


def test_verify_refuses_a_link_in_the_output(tmp_path: Path) -> None:
    _winapi = pytest.importorskip("_winapi")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    _winapi.CreateJunction(str(elsewhere), str(output / "link"))
    with pytest.raises(ArchiveProblem) as problem:
        verify_output(output, _listing())
    assert problem.value.code == "special_entry"
