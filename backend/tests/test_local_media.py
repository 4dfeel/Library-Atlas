"""Audio through the real API, with real files and real range requests. All sound is made here."""

import struct
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.core.config import Settings
from app.db.schema import personal_records, works
from app.services.local_media import natural_key, path_key
from tests.conftest import client_for
from tests.test_downloads import Rig, engine_of, first_work, prepare


def wav(seconds: float = 1.0) -> bytes:
    rate = 8000
    frames = int(rate * seconds)
    data = b"\x80" * frames
    return (
        b"RIFF"
        + struct.pack("<I", 36 + frames)
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate, 1, 8)
        + b"data"
        + struct.pack("<I", frames)
        + data
    )


@pytest.fixture
def rig(settings: Settings, tmp_path: Path) -> Rig:
    return Rig(settings, tmp_path)


@pytest.fixture
def api(settings: Settings, rig: Rig) -> Iterator[TestClient]:
    with client_for(settings) as client:
        prepare(client, rig)
        with engine_of(client).begin() as connection:
            connection.execute(update(works).values(kind="audio"))
        yield client


@pytest.fixture
def album(tmp_path: Path) -> Path:
    folder = tmp_path / "音声 作品"
    (folder / "本編").mkdir(parents=True)
    (folder / "おまけ").mkdir()
    for name in ("10.wav", "2.wav", "1 はじめに.mp3"):
        (folder / "本編" / name).write_bytes(wav())
    (folder / "おまけ" / "bonus.flac").write_bytes(wav())
    (folder / "おまけ" / "old.wma").write_bytes(b"x")
    (folder / "readme.txt").write_bytes(b"text")
    (folder / "cover.jpg").write_bytes(b"image")
    return folder


def link(client: TestClient, folder: Path) -> tuple[dict[str, Any], str]:
    work = first_work(client)
    response = client.post(f"/api/v1/works/{work['id']}/local-copies", json={"root": str(folder)})
    assert response.status_code == 200
    copy_id: str = response.json()["copies"][0]["id"]
    return work, copy_id


def tracks(client: TestClient, work_id: str) -> dict[str, Any]:
    result: dict[str, Any] = client.get(f"/api/v1/works/{work_id}/audio").json()
    return result


def track_named(data: dict[str, Any], name: str) -> dict[str, Any]:
    found: dict[str, Any] = next(track for track in data["tracks"] if track["name"] == name)
    return found


# --- ordering ---


def test_numbers_sort_as_a_person_counts() -> None:
    names = ["10.wav", "2.wav", "1.wav", "B.wav", "a.wav"]
    assert sorted(names, key=natural_key) == ["1.wav", "2.wav", "10.wav", "a.wav", "B.wav"]
    assert sorted(["b/1.wav", "a/10.wav", "a/2.wav"], key=path_key) == [
        "a/2.wav",
        "a/10.wav",
        "b/1.wav",
    ]


# --- the list ---


def test_audio_is_found_in_order_and_nothing_else_is_listed(api: TestClient, album: Path) -> None:
    work, _copy = link(api, album)
    data = tracks(api, work["id"])
    assert data["state"] == "ready"
    assert [(item["folder"], item["name"]) for item in data["tracks"]] == [
        ("おまけ", "bonus.flac"),
        ("おまけ", "old.wma"),
        ("本編", "1 はじめに.mp3"),
        ("本編", "2.wav"),
        ("本編", "10.wav"),
    ]


def test_a_format_a_browser_cannot_play_is_shown_as_such(api: TestClient, album: Path) -> None:
    work, _copy = link(api, album)
    assert track_named(tracks(api, work["id"]), "old.wma")["playable"] is False
    assert track_named(tracks(api, work["id"]), "2.wav")["playable"] is True


@pytest.mark.parametrize("empty", ["no_copy", "empty"])
def test_nothing_to_play_says_why(api: TestClient, tmp_path: Path, empty: str) -> None:
    work = first_work(api)
    if empty == "empty":
        folder = tmp_path / "nothing"
        folder.mkdir()
        link(api, folder)
    assert tracks(api, work["id"])["state"] == empty


def test_an_offline_folder_is_not_an_empty_one(api: TestClient, album: Path) -> None:
    from app.db.schema import local_copies

    work, _copy = link(api, album)
    with engine_of(api).begin() as connection:
        connection.execute(update(local_copies).values(root_path="Z:\\未连接\\音声"))
    assert tracks(api, work["id"])["state"] == "offline"


def test_links_are_not_followed(api: TestClient, tmp_path: Path) -> None:
    winapi = pytest.importorskip("_winapi")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.wav").write_bytes(wav())
    folder = tmp_path / "album"
    folder.mkdir()
    (folder / "ok.wav").write_bytes(wav())
    winapi.CreateJunction(str(outside), str(folder / "link"))
    work, _copy = link(api, folder)
    assert [item["name"] for item in tracks(api, work["id"])["tracks"]] == ["ok.wav"]


# --- streaming ---


def test_a_track_streams_with_ranges(api: TestClient, album: Path) -> None:
    work, copy_id = link(api, album)
    track = track_named(tracks(api, work["id"]), "2.wav")
    url = f"/api/v1/media/audio/{copy_id}/{track['id']}"
    whole = api.get(url)
    assert whole.status_code == 200
    assert whole.headers["content-type"].startswith("audio/wav")
    assert whole.headers["accept-ranges"] == "bytes"
    assert whole.content == wav()
    part = api.get(url, headers={"Range": "bytes=100-199"})
    assert part.status_code == 206
    assert part.content == wav()[100:200]
    assert part.headers["content-range"] == f"bytes 100-199/{len(wav())}"


@pytest.mark.parametrize(
    "track",
    ["..%2F..%2Fsecret.txt", "..%5C..%5Csecret.txt", "C%3A%5CWindows%5Cwin.ini", "abc"],
)
def test_a_request_cannot_reach_a_path(api: TestClient, album: Path, track: str) -> None:
    _work, copy_id = link(api, album)
    assert api.get(f"/api/v1/media/audio/{copy_id}/{track}").status_code == 404


def test_an_unknown_copy_is_nothing(api: TestClient) -> None:
    assert api.get("/api/v1/media/audio/nope/nope").status_code == 404


def test_other_files_in_the_folder_are_not_served(api: TestClient, album: Path) -> None:
    from app.services.local_media import _file_id

    _work, copy_id = link(api, album)
    assert (
        api.get(f"/api/v1/media/audio/{copy_id}/{_file_id(copy_id, 'readme.txt')}").status_code
        == 404
    )


def test_a_file_gone_since_it_was_listed_is_a_plain_404(api: TestClient, album: Path) -> None:
    work, copy_id = link(api, album)
    track = track_named(tracks(api, work["id"]), "2.wav")
    (album / "本編" / "2.wav").unlink()
    assert api.get(f"/api/v1/media/audio/{copy_id}/{track['id']}").status_code == 404


@pytest.mark.parametrize("visibility", ["hidden", "private", "quarantined"])
def test_works_outside_ordinary_views_are_silent(
    api: TestClient, album: Path, visibility: str
) -> None:
    work, copy_id = link(api, album)
    track = track_named(tracks(api, work["id"]), "2.wav")
    with engine_of(api).begin() as connection:
        connection.execute(
            update(personal_records)
            .where(personal_records.c.work_id == work["id"])
            .values(visibility=visibility)
        )
    assert api.get(f"/api/v1/media/audio/{copy_id}/{track['id']}").status_code == 404
    assert api.get(f"/api/v1/works/{work['id']}/audio").status_code == 404


# --- progress ---


def save(client: TestClient, copy_id: str, track_id: str, position: float) -> None:
    response = client.put(
        "/api/v1/media/audio-progress",
        json={"copyId": copy_id, "trackId": track_id, "position": position, "duration": 100},
    )
    assert response.status_code == 200, response.text


def test_position_is_kept_and_the_last_track_is_remembered(api: TestClient, album: Path) -> None:
    work, copy_id = link(api, album)
    first = track_named(tracks(api, work["id"]), "2.wav")
    second = track_named(tracks(api, work["id"]), "10.wav")
    save(api, copy_id, first["id"], 12.5)
    save(api, copy_id, second["id"], 3)
    data = tracks(api, work["id"])
    assert track_named(data, "2.wav")["position"] == 12.5
    assert track_named(data, "2.wav")["duration"] == 100
    assert data["lastTrackId"] == second["id"]


def test_a_changed_file_does_not_inherit_the_old_position(api: TestClient, album: Path) -> None:
    work, copy_id = link(api, album)
    track = track_named(tracks(api, work["id"]), "2.wav")
    save(api, copy_id, track["id"], 40)
    (album / "本編" / "2.wav").write_bytes(wav(3))
    service = api.app.state.service.media  # type: ignore[attr-defined]
    service.forget(copy_id)
    data = tracks(api, work["id"])
    assert track_named(data, "2.wav")["position"] == 0
    assert data["lastTrackId"] is None


def test_progress_survives_a_restart(settings: Settings, rig: Rig, album: Path) -> None:
    with client_for(settings) as client:
        prepare(client, rig)
        with engine_of(client).begin() as connection:
            connection.execute(update(works).values(kind="audio"))
        work, copy_id = link(client, album)
        track = track_named(tracks(client, work["id"]), "2.wav")
        save(client, copy_id, track["id"], 7)
    with client_for(settings) as client:
        assert track_named(tracks(client, work["id"]), "2.wav")["position"] == 7


@pytest.mark.parametrize("position", [-1, float("inf")])
def test_nonsense_positions_are_refused(api: TestClient, album: Path, position: float) -> None:
    work, copy_id = link(api, album)
    track = track_named(tracks(api, work["id"]), "2.wav")
    number = "-1" if position == -1 else "1e999"
    body = f'{{"copyId":"{copy_id}","trackId":"{track["id"]}","position":{number}}}'
    response = api.put(
        "/api/v1/media/audio-progress",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422


# --- bookmarks ---


def test_bookmarks_come_and_go(api: TestClient, album: Path) -> None:
    work, copy_id = link(api, album)
    track = track_named(tracks(api, work["id"]), "2.wav")
    added = api.post(
        "/api/v1/media/audio-bookmarks",
        json={"copyId": copy_id, "resourceId": track["id"], "position": 33, "label": " 这里 "},
    )
    assert added.status_code == 200
    listed = api.get(f"/api/v1/works/{work['id']}/audio/bookmarks").json()["bookmarks"]
    assert listed[0]["position"] == 33
    assert listed[0]["label"] == "这里"
    assert api.delete(f"/api/v1/audio-bookmarks/{listed[0]['id']}").status_code == 200
    assert api.get(f"/api/v1/works/{work['id']}/audio/bookmarks").json()["bookmarks"] == []


def test_a_file_moving_away_does_not_delete_bookmarks(api: TestClient, album: Path) -> None:
    work, copy_id = link(api, album)
    track = track_named(tracks(api, work["id"]), "2.wav")
    api.post(
        "/api/v1/media/audio-bookmarks",
        json={"copyId": copy_id, "resourceId": track["id"], "position": 5},
    )
    (album / "本編" / "2.wav").unlink()
    api.app.state.service.media.forget(copy_id)  # type: ignore[attr-defined]
    assert len(api.get(f"/api/v1/works/{work['id']}/audio/bookmarks").json()["bookmarks"]) == 1


# --- playlists ---


def test_a_playlist_keeps_its_order_and_a_rescan_does_not_touch_it(
    api: TestClient, album: Path
) -> None:
    work, copy_id = link(api, album)
    data = tracks(api, work["id"])
    items = [
        {"copyId": copy_id, "trackId": track["id"], "workId": work["id"], "name": track["name"]}
        for track in reversed(data["tracks"][:3])
    ]
    saved = api.post("/api/v1/media/playlists", json={"name": "睡前", "items": items}).json()
    assert saved["playlists"][0]["name"] == "睡前"
    assert [item["trackId"] for item in saved["playlists"][0]["items"]] == [
        item["trackId"] for item in items
    ]
    api.app.state.service.media.forget(copy_id)  # type: ignore[attr-defined]
    tracks(api, work["id"])
    listed = api.get("/api/v1/media/playlists").json()["playlists"]
    assert len(listed[0]["items"]) == 3
    assert api.delete(f"/api/v1/media/playlists/{listed[0]['id']}").status_code == 200
    assert api.get("/api/v1/media/playlists").json()["playlists"] == []


def test_a_hidden_work_drops_out_of_playlists(api: TestClient, album: Path) -> None:
    work, copy_id = link(api, album)
    track = tracks(api, work["id"])["tracks"][0]
    api.post(
        "/api/v1/media/playlists",
        json={
            "name": "列表",
            "items": [
                {"copyId": copy_id, "trackId": track["id"], "workId": work["id"], "name": "x"}
            ],
        },
    )
    with engine_of(api).begin() as connection:
        connection.execute(
            update(personal_records)
            .where(personal_records.c.work_id == work["id"])
            .values(visibility="private")
        )
    assert api.get("/api/v1/media/playlists").json()["playlists"][0]["items"] == []


def test_a_large_album_is_listed_quickly_and_only_once(api: TestClient, tmp_path: Path) -> None:
    import time

    folder = tmp_path / "large"
    folder.mkdir()
    for index in range(3000):
        (folder / f"{index}.wav").write_bytes(b"x")
    work, _copy = link(api, folder)
    began = time.monotonic()
    first = tracks(api, work["id"])
    first_time = time.monotonic() - began
    assert len(first["tracks"]) == 3000
    assert first["complete"] is True
    assert first["tracks"][9]["name"] == "9.wav"
    assert first["tracks"][10]["name"] == "10.wav"
    began = time.monotonic()
    tracks(api, work["id"])
    assert time.monotonic() - began <= max(first_time * 2, 1.0)
