"""The reader through the real API, with real files and real archives. Every page is made here."""

import struct
import zipfile
import zlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.core.config import Settings
from app.db.schema import personal_records, works
from app.domain.image_header import ImageHeader, acceptable, read_header
from tests.conftest import client_for
from tests.test_downloads import Rig, engine_of, first_work, prepare


def png(width: int = 2, height: int = 2) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data)
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    rows = (b"\x00" + b"\xff" * width * 3) * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def rig(settings: Settings, tmp_path: Path) -> Rig:
    return Rig(settings, tmp_path)


@pytest.fixture
def api(settings: Settings, rig: Rig) -> Iterator[TestClient]:
    with client_for(settings) as client:
        prepare(client, rig)
        with engine_of(client).begin() as connection:
            connection.execute(update(works).values(kind="image"))
        yield client


@pytest.fixture
def shelf(tmp_path: Path) -> Path:
    folder = tmp_path / "漫画 作品"
    for volume in ("第1巻", "第2巻", "おまけ"):
        (folder / volume).mkdir(parents=True)
    for name in ("10.png", "2.png", "1.png"):
        (folder / "第1巻" / name).write_bytes(png())
    (folder / "第2巻" / "a.png").write_bytes(png())
    (folder / "おまけ" / "bonus.png").write_bytes(png())
    (folder / "第1巻" / "notes.txt").write_text("x")
    (folder / "extra.rar").write_bytes(b"Rar!")
    return folder


def link(client: TestClient, folder: Path) -> tuple[dict[str, Any], str]:
    work = first_work(client)
    response = client.post(f"/api/v1/works/{work['id']}/local-copies", json={"root": str(folder)})
    assert response.status_code == 200
    copy_id: str = response.json()["copies"][0]["id"]
    return work, copy_id


def books(client: TestClient, work_id: str) -> dict[str, Any]:
    result: dict[str, Any] = client.get(f"/api/v1/works/{work_id}/books").json()
    return result


def book_named(data: dict[str, Any], name: str) -> dict[str, Any]:
    found: dict[str, Any] = next(book for book in data["books"] if book["name"] == name)
    return found


def pages(client: TestClient, copy_id: str, book_id: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/media/books/{copy_id}/{book_id}/pages")
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


# --- headers ---


def test_the_header_decides_what_a_file_is() -> None:
    assert read_header(png()) == ImageHeader("image/png", 2, 2)
    assert read_header(b"GIF89a" + struct.pack("<HH", 3, 4)) == ImageHeader("image/gif", 3, 4)
    jpeg = b"\xff\xd8\xff\xe0\x00\x04\x00\x00\xff\xc0\x00\x11\x08\x00\x05\x00\x06" + b"\0" * 8
    assert read_header(jpeg) == ImageHeader("image/jpeg", 6, 5)
    assert read_header(b"<svg></svg>") is None
    assert read_header(b"plain text") is None


@pytest.mark.parametrize(
    ("width", "height", "fine"),
    [(1000, 30000, True), (70000, 10, False), (30000, 30000, False), (0, 10, False)],
)
def test_absurd_sizes_are_refused(width: int, height: int, fine: bool) -> None:
    assert acceptable(ImageHeader("image/png", width, height)) is fine


# --- finding books ---


def test_each_folder_is_its_own_book_in_natural_order(api: TestClient, shelf: Path) -> None:
    work, copy_id = link(api, shelf)
    data = books(api, work["id"])
    assert data["state"] == "ready"
    assert [book["name"] for book in data["books"]] == ["おまけ", "第1巻", "第2巻"]
    volume = book_named(data, "第1巻")
    assert volume["pageCount"] == 3
    assert [page["name"] for page in pages(api, copy_id, volume["id"])["pages"]] == [
        "1.png",
        "2.png",
        "10.png",
    ]


def test_what_cannot_be_opened_is_listed_with_the_reason(api: TestClient, shelf: Path) -> None:
    work, _copy = link(api, shelf)
    unsupported = books(api, work["id"])["unsupported"]
    assert [item["name"] for item in unsupported] == ["extra.rar"]
    assert "RAR" in unsupported[0]["reason"]


@pytest.mark.parametrize("state", ["no_copy", "empty", "offline"])
def test_nothing_to_read_says_why(api: TestClient, tmp_path: Path, state: str) -> None:
    from app.db.schema import local_copies

    work = first_work(api)
    if state != "no_copy":
        folder = tmp_path / "nothing"
        folder.mkdir()
        link(api, folder)
    if state == "offline":
        with engine_of(api).begin() as connection:
            connection.execute(update(local_copies).values(root_path="Z:\\未连接"))
    assert books(api, work["id"])["state"] == state


def test_links_are_not_followed(api: TestClient, tmp_path: Path) -> None:
    winapi = pytest.importorskip("_winapi")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.png").write_bytes(png())
    folder = tmp_path / "book"
    folder.mkdir()
    (folder / "ok.png").write_bytes(png())
    winapi.CreateJunction(str(outside), str(folder / "link"))
    work, _copy = link(api, folder)
    assert [book["name"] for book in books(api, work["id"])["books"]] == ["根目录"]


# --- image pages ---


def test_a_page_is_served_as_what_it_is(api: TestClient, shelf: Path) -> None:
    work, copy_id = link(api, shelf)
    book = book_named(books(api, work["id"]), "第1巻")
    page = pages(api, copy_id, book["id"])["pages"][0]
    response = api.get(f"/api/v1/media/pages/{copy_id}/{book['id']}/{page['id']}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == png()


@pytest.mark.parametrize("content", [b"<svg onload='x'></svg>", b"not an image"])
def test_a_page_pretending_to_be_an_image_is_refused(
    api: TestClient, tmp_path: Path, content: bytes
) -> None:
    folder = tmp_path / "fake"
    folder.mkdir()
    (folder / "1.png").write_bytes(content)
    (folder / "2.png").write_bytes(png())
    work, copy_id = link(api, folder)
    book = books(api, work["id"])["books"][0]
    listed = pages(api, copy_id, book["id"])["pages"]
    url = f"/api/v1/media/pages/{copy_id}/{book['id']}"
    assert api.get(f"{url}/{listed[0]['id']}").status_code == 415
    # The bad one does not take the book down with it.
    assert api.get(f"{url}/{listed[1]['id']}").status_code == 200


def test_a_declared_giant_is_refused_before_anything_decodes_it(
    api: TestClient, tmp_path: Path
) -> None:
    folder = tmp_path / "giant"
    folder.mkdir()
    (folder / "1.png").write_bytes(png(40000, 1)[:33])
    work, copy_id = link(api, folder)
    book = books(api, work["id"])["books"][0]
    giant = b"\x89PNG\r\n\x1a\n" + b"\0\0\0\x0dIHDR" + struct.pack(">II", 60000, 60000)
    (folder / "1.png").write_bytes(giant)
    api.app.state.service.media.forget(copy_id)  # type: ignore[attr-defined]
    page = pages(api, copy_id, book["id"])["pages"][0]
    assert api.get(f"/api/v1/media/pages/{copy_id}/{book['id']}/{page['id']}").status_code == 415


@pytest.mark.parametrize("page", ["..%2F..%2Fsecret", "C%3A%5CWindows%5Cwin.ini", "abc"])
def test_a_request_cannot_reach_a_path(api: TestClient, shelf: Path, page: str) -> None:
    work, copy_id = link(api, shelf)
    book = books(api, work["id"])["books"][0]
    assert api.get(f"/api/v1/media/pages/{copy_id}/{book['id']}/{page}").status_code == 404


@pytest.mark.parametrize("visibility", ["hidden", "private", "quarantined"])
def test_works_outside_ordinary_views_are_silent(
    api: TestClient, shelf: Path, visibility: str
) -> None:
    work, copy_id = link(api, shelf)
    book = book_named(books(api, work["id"]), "第1巻")
    page = pages(api, copy_id, book["id"])["pages"][0]
    with engine_of(api).begin() as connection:
        connection.execute(
            update(personal_records)
            .where(personal_records.c.work_id == work["id"])
            .values(visibility=visibility)
        )
    assert api.get(f"/api/v1/works/{work['id']}/books").status_code == 404
    assert api.get(f"/api/v1/media/books/{copy_id}/{book['id']}/pages").status_code == 404
    url = f"/api/v1/media/pages/{copy_id}/{book['id']}/{page['id']}"
    assert api.get(url).status_code == 404


# --- archives ---


def make_cbz(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)


def test_an_archive_reads_in_place_and_nothing_is_unpacked(api: TestClient, tmp_path: Path) -> None:
    folder = tmp_path / "cbz"
    folder.mkdir()
    make_cbz(
        folder / "本.cbz",
        {
            "第一章/10.png": png(),
            "第一章/2.png": png(3),
            "第二章/1.png": png(),
            "info.txt": b"x",
            "inner.zip": b"PK",
        },
    )
    work, copy_id = link(api, folder)
    book = books(api, work["id"])["books"][0]
    assert book["kind"] == "archive"
    data = pages(api, copy_id, book["id"])
    assert [(page["section"], page["name"]) for page in data["pages"]] == [
        ("第一章", "2.png"),
        ("第一章", "10.png"),
        ("第二章", "1.png"),
    ]
    response = api.get(f"/api/v1/media/pages/{copy_id}/{book['id']}/{data['pages'][0]['id']}")
    assert response.status_code == 200
    assert response.content == png(3)
    assert [item.name for item in folder.iterdir()] == ["本.cbz"]


def test_japanese_names_without_a_utf8_flag_read_correctly(api: TestClient, tmp_path: Path) -> None:
    folder = tmp_path / "cp932"
    folder.mkdir()
    # A stored entry written by hand: the name is cp932 and the UTF-8 flag is clear.
    name = "表紙.png".encode("cp932")
    content = png()
    crc = zlib.crc32(content)
    size = len(content)
    local = struct.pack("<4s5H3I2H", b"PK\x03\x04", 20, 0, 0, 0, 0, crc, size, size, len(name), 0)
    central = struct.pack(
        "<4s6H3I5H2I",
        b"PK\x01\x02",
        20,
        20,
        0,
        0,
        0,
        0,
        crc,
        size,
        size,
        len(name),
        0,
        0,
        0,
        0,
        0,
        0,
    )
    body = local + name + content
    end = struct.pack("<4s4H2IH", b"PK\x05\x06", 0, 0, 1, 1, len(central) + len(name), len(body), 0)
    (folder / "a.zip").write_bytes(body + central + name + end)
    work, copy_id = link(api, folder)
    book = books(api, work["id"])["books"][0]
    assert pages(api, copy_id, book["id"])["pages"][0]["name"] == "表紙.png"


def test_unsafe_members_are_counted_not_served(api: TestClient, tmp_path: Path) -> None:
    folder = tmp_path / "evil"
    folder.mkdir()
    make_cbz(folder / "evil.zip", {"../../escape.png": png(), "ok.png": png()})
    work, copy_id = link(api, folder)
    book = books(api, work["id"])["books"][0]
    data = pages(api, copy_id, book["id"])
    assert [page["name"] for page in data["pages"]] == ["ok.png"]
    assert data["skipped"] == 1


def test_a_member_built_to_blow_up_is_refused(api: TestClient, tmp_path: Path) -> None:
    folder = tmp_path / "bomb"
    folder.mkdir()
    with zipfile.ZipFile(folder / "bomb.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bomb.png", b"\0" * (32 * 1024 * 1024))
        archive.writestr("ok.png", png())
    work, copy_id = link(api, folder)
    book = books(api, work["id"])["books"][0]
    data = pages(api, copy_id, book["id"])
    assert [page["name"] for page in data["pages"]] == ["ok.png"]
    assert data["skipped"] == 1


def test_a_damaged_archive_is_said_and_the_rest_still_opens(
    api: TestClient, tmp_path: Path
) -> None:
    folder = tmp_path / "broken"
    folder.mkdir()
    (folder / "broken.zip").write_bytes(b"PK not really")
    (folder / "ok").mkdir()
    (folder / "ok" / "1.png").write_bytes(png())
    work, copy_id = link(api, folder)
    data = books(api, work["id"])
    assert (
        api.get(
            f"/api/v1/media/books/{copy_id}/{book_named(data, 'broken.zip')['id']}/pages"
        ).status_code
        == 422
    )
    assert pages(api, copy_id, book_named(data, "ok")["id"])["pages"]


# --- PDF ---


def test_a_pdf_is_served_with_ranges_and_checked_first(api: TestClient, tmp_path: Path) -> None:
    folder = tmp_path / "pdf"
    folder.mkdir()
    (folder / "ok.pdf").write_bytes(b"%PDF-1.4\n" + b"0" * 2000)
    (folder / "fake.pdf").write_bytes(b"<html></html>")
    work, copy_id = link(api, folder)
    data = books(api, work["id"])
    good = book_named(data, "ok.pdf")
    assert good["kind"] == "pdf"
    url = f"/api/v1/media/books/{copy_id}/{good['id']}/file"
    assert api.get(url).headers["content-type"] == "application/pdf"
    part = api.get(url, headers={"Range": "bytes=0-7"})
    assert part.status_code == 206
    assert part.content == b"%PDF-1.4"
    fake = book_named(data, "fake.pdf")["id"]
    assert api.get(f"/api/v1/media/books/{copy_id}/{fake}/file").status_code == 422


# --- where the user is ---


def go_to(
    client: TestClient,
    copy_id: str,
    book: dict[str, Any],
    page: dict[str, Any],
    index: int,
    **rest: Any,
) -> None:
    response = client.put(
        "/api/v1/media/reading",
        json={
            "copyId": copy_id,
            "bookId": book["id"],
            "pageId": page["id"],
            "pageIndex": index,
            "pageCount": book["pageCount"],
            **rest,
        },
    )
    assert response.status_code == 200, response.text


def test_the_place_survives_a_restart_and_the_last_book_is_remembered(
    settings: Settings, rig: Rig, shelf: Path
) -> None:
    with client_for(settings) as client:
        prepare(client, rig)
        with engine_of(client).begin() as connection:
            connection.execute(update(works).values(kind="image"))
        work, copy_id = link(client, shelf)
        book = book_named(books(client, work["id"]), "第1巻")
        page = pages(client, copy_id, book["id"])["pages"][1]
        go_to(client, copy_id, book, page, 1)
    with client_for(settings) as client:
        data = books(client, work["id"])
        assert data["lastBookId"] == book["id"]
        assert book_named(data, "第1巻")["pageIndex"] == 1
        assert book_named(data, "第1巻")["readState"] == "reading"
        again = pages(client, copy_id, book["id"])
        assert again["pageId"] == page["id"]


def test_a_replaced_page_is_not_mistaken_for_the_old_one(api: TestClient, shelf: Path) -> None:
    work, copy_id = link(api, shelf)
    book = book_named(books(api, work["id"]), "第1巻")
    before = pages(api, copy_id, book["id"])["pages"]
    go_to(api, copy_id, book, before[1], 1)
    (shelf / "第1巻" / "2.png").write_bytes(png(9, 9))
    api.app.state.service.media.forget(copy_id)  # type: ignore[attr-defined]
    after = pages(api, copy_id, book["id"])
    assert after["pageId"] == before[1]["id"]
    assert after["pageId"] not in [page["id"] for page in after["pages"]]
    assert after["pages"][0]["id"] == before[0]["id"]


def test_a_new_page_does_not_shift_the_place(api: TestClient, shelf: Path) -> None:
    work, copy_id = link(api, shelf)
    book = book_named(books(api, work["id"]), "第1巻")
    before = pages(api, copy_id, book["id"])["pages"]
    go_to(api, copy_id, book, before[1], 1)
    (shelf / "第1巻" / "0.png").write_bytes(png())
    api.app.state.service.media.forget(copy_id)  # type: ignore[attr-defined]
    after = pages(api, copy_id, book["id"])
    assert [page["id"] for page in after["pages"]].index(after["pageId"]) == 2


def test_read_means_finished_or_said_so_never_just_opened(api: TestClient, shelf: Path) -> None:
    work, copy_id = link(api, shelf)
    book = book_named(books(api, work["id"]), "第1巻")
    assert book["readState"] == "unread"
    listed = pages(api, copy_id, book["id"])["pages"]
    assert book_named(books(api, work["id"]), "第1巻")["readState"] == "unread"
    go_to(api, copy_id, book, listed[0], 0)
    assert book_named(books(api, work["id"]), "第1巻")["readState"] == "reading"
    go_to(api, copy_id, book, listed[2], 2, finished=True)
    assert book_named(books(api, work["id"]), "第1巻")["readState"] == "read"
    # Going back to look at something does not unread it.
    go_to(api, copy_id, book, listed[0], 0)
    assert book_named(books(api, work["id"]), "第1巻")["readState"] == "read"
    response = api.put(
        "/api/v1/media/read-state", json={"copyId": copy_id, "bookId": book["id"], "read": False}
    )
    assert response.status_code == 200
    assert book_named(books(api, work["id"]), "第1巻")["readState"] == "unread"


def test_bookmarks_come_and_go_and_outlive_their_file(api: TestClient, shelf: Path) -> None:
    work, copy_id = link(api, shelf)
    book = book_named(books(api, work["id"]), "第1巻")
    listed = pages(api, copy_id, book["id"])["pages"]
    added = api.post(
        "/api/v1/media/reader-bookmarks",
        json={"copyId": copy_id, "bookId": book["id"], "pageId": listed[1]["id"], "pageIndex": 1},
    )
    assert added.status_code == 200
    (shelf / "第1巻" / "2.png").unlink()
    api.app.state.service.media.forget(copy_id)  # type: ignore[attr-defined]
    url = f"/api/v1/media/books/{copy_id}/{book['id']}/bookmarks"
    marks = api.get(url).json()["bookmarks"]
    assert [mark["pageId"] for mark in marks] == [listed[1]["id"]]
    assert api.delete(f"/api/v1/reader-bookmarks/{marks[0]['id']}").status_code == 200
    assert api.get(url).json()["bookmarks"] == []


@pytest.mark.parametrize("index", [-1, 2_000_000])
def test_nonsense_places_are_refused(api: TestClient, shelf: Path, index: int) -> None:
    work, copy_id = link(api, shelf)
    book = book_named(books(api, work["id"]), "第1巻")
    response = api.put(
        "/api/v1/media/reading",
        json={"copyId": copy_id, "bookId": book["id"], "pageId": "x", "pageIndex": index},
    )
    assert response.status_code == 422


def test_a_large_book_is_listed_whole_without_reading_its_pages(
    api: TestClient, tmp_path: Path
) -> None:
    folder = tmp_path / "large"
    folder.mkdir()
    for index in range(3000):
        (folder / f"{index}.png").write_bytes(b"")
    work, copy_id = link(api, folder)
    book = books(api, work["id"])["books"][0]
    assert book["pageCount"] == 3000
    listed = pages(api, copy_id, book["id"])["pages"]
    assert listed[10]["name"] == "10.png"
