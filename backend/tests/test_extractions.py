"""Download and unpack through the whole backend: the real API and queues, real sockets, real
files and the real 7-Zip. The archives are synthetic and the platform is pretend."""

import shutil
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.adapters.system.archives import ArchiveProblem, find_seven_zip
from app.core.config import Settings
from app.db.schema import extract_tasks, personal_records
from app.services import extractions as extractions_module
from tests import archive_samples as samples
from tests.conftest import client_for, write_headers
from tests.test_downloads import (
    Rig,
    ended,
    engine_of,
    final_files,
    first_work,
    prepare,
    start,
    work_ids,
)

BASE = "/api/v1/extractions"
ACTIVE = ("queued", "checking", "extracting", "committing")


@pytest.fixture
def rig(settings: Settings, tmp_path: Path) -> Rig:
    return Rig(settings, tmp_path)


@pytest.fixture
def unpack_root(tmp_path: Path) -> Path:
    folder = tmp_path / "解压 フォルダ"
    folder.mkdir()
    return folder


@pytest.fixture
def api(settings: Settings, rig: Rig, unpack_root: Path) -> Iterator[TestClient]:
    with client_for(settings) as client:
        prepare(client, rig)
        response = client.put("/api/v1/settings/folders/extract", json={"path": str(unpack_root)})
        assert response.status_code == 200
        yield client


@pytest.fixture
def archives(tmp_path: Path) -> Path:
    folder = tmp_path / "samples"
    folder.mkdir()
    return folder


def serve(rig: Rig, path: Path | list[Path], **extra: Any) -> None:
    payload = [str(item) for item in path] if isinstance(path, list) else str(path)
    rig.behave(payload=payload, **extra)


def extraction_of(client: TestClient, work_id: str) -> dict[str, Any] | None:
    for task in client.get(BASE).json()["tasks"]:
        if task["workId"] == work_id:
            result: dict[str, Any] = task
            return result
    return None


def settled(client: TestClient, work_id: str, seconds: float = 30) -> dict[str, Any]:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        task = extraction_of(client, work_id)
        if task and task["state"] not in ACTIVE:
            return task
        time.sleep(0.02)
    raise AssertionError("timed out")


def download_only(client: TestClient, work_id: str) -> None:
    for task in start(client, work_id):
        assert ended(client, task["id"])["state"] == "done"


def unpack(client: TestClient, work_id: str, **body: Any) -> dict[str, Any]:
    response = client.post(BASE, json={"workId": work_id, **body})
    assert response.status_code == 202, response.text
    return settled(client, work_id)


def tree(folder: Path) -> list[str]:
    return sorted(
        path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()
    )


# --- the whole way ---


def test_one_click_downloads_then_unpacks(
    api: TestClient, rig: Rig, archives: Path, unpack_root: Path
) -> None:
    archive = samples.zip_with(
        archives / "a.zip", {"音声/01 はじめに.wav": b"a" * 1000, "説明.txt": b"b"}
    )
    serve(rig, archive)
    work = first_work(api)
    tasks = start(api, work["id"], extract=True)
    assert ended(api, tasks[0]["id"])["state"] == "done"
    done = settled(api, work["id"])
    assert done["state"] == "done", done
    assert done["format"] == "zip"
    assert done["filesTotal"] == 2
    assert done["bytesTotal"] == 1001
    result = unpack_root / work["sourceId"]
    assert done["location"] == str(result)
    assert tree(result) == ["说明.txt".replace("说", "説"), "音声/01 はじめに.wav"]
    assert (result / "音声" / "01 はじめに.wav").read_bytes() == b"a" * 1000
    # The download stays, and nothing was left behind.
    assert len(final_files(rig)) == 1
    assert [path.name for path in unpack_root.iterdir()] == [work["sourceId"]]


def test_a_download_alone_never_starts_unpacking(
    api: TestClient, rig: Rig, archives: Path, unpack_root: Path
) -> None:
    serve(rig, samples.zip_with(archives / "a.zip", {"a.txt": b"x"}))
    work = first_work(api)
    download_only(api, work["id"])
    time.sleep(0.3)
    assert api.get(BASE).json()["tasks"] == []
    assert list(unpack_root.iterdir()) == []


def test_a_finished_download_can_be_unpacked_later(
    api: TestClient, rig: Rig, archives: Path, unpack_root: Path
) -> None:
    serve(rig, samples.zip_with(archives / "a.zip", {"a.txt": b"x"}))
    work = first_work(api)
    download_only(api, work["id"])
    assert unpack(api, work["id"])["state"] == "done"
    assert (unpack_root / work["sourceId"] / "a.txt").read_bytes() == b"x"


def test_one_click_on_a_finished_download_does_not_download_again(
    api: TestClient, rig: Rig, archives: Path
) -> None:
    serve(rig, samples.zip_with(archives / "a.zip", {"a.txt": b"x"}))
    work = first_work(api)
    download_only(api, work["id"])
    files_before = final_files(rig)
    start(api, work["id"], extract=True)
    assert settled(api, work["id"])["state"] == "done"
    assert final_files(rig) == files_before


def test_split_rar_goes_through_with_every_part(
    api: TestClient, rig: Rig, archives: Path, unpack_root: Path
) -> None:
    if find_seven_zip() is None:
        pytest.skip("needs 7-Zip")
    data = bytes(range(256)) * 600
    work = first_work(api)
    # Parts are named by the server after the work, as the real route does.
    parts = samples.rar_volumes(archives, work["sourceId"], "movie.bin", data, 3)
    serve(rig, parts, parts=3)
    tasks = start(api, work["id"], extract=True)
    assert len(tasks) == 3
    done = settled(api, work["id"])
    assert done["state"] == "done", done
    assert done["format"] == "rar"
    assert (unpack_root / work["sourceId"] / "movie.bin").read_bytes() == data


def test_unpacking_waits_for_every_part(api: TestClient, rig: Rig, archives: Path) -> None:
    work = first_work(api)
    parts = samples.rar_volumes(archives, work["sourceId"], "m.bin", bytes(90_000), 3)
    serve(rig, parts, parts=3)
    for task in start(api, work["id"], parts=[1, 2], extract=True):
        ended(api, task["id"])
    # Only the chosen parts finished: the wish stands, but it cannot be met yet.
    task = extraction_of(api, work["id"])
    assert task is None
    response = api.post(BASE, json={"workId": work["id"]})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "missing_parts"


def test_a_file_that_is_not_an_archive_skips_unpacking(
    api: TestClient, rig: Rig, unpack_root: Path
) -> None:
    rig.behave(size=2000)  # Made-up bytes with no archive signature.
    work = first_work(api)
    start(api, work["id"], extract=True)
    done = settled(api, work["id"])
    assert done["state"] == "not_needed"
    assert done["location"] is None
    assert list(unpack_root.iterdir()) == []


def test_a_plain_program_skips_unpacking_and_is_never_run(
    api: TestClient, rig: Rig, unpack_root: Path, archives: Path
) -> None:
    tool = find_seven_zip()
    if tool is None:
        pytest.skip("needs 7-Zip")
    program = archives / "program.exe"
    shutil.copyfile(tool.executable, program)
    serve(rig, program)
    work = first_work(api)
    start(api, work["id"], extract=True)
    assert settled(api, work["id"])["state"] == "not_needed"
    assert list(unpack_root.iterdir()) == []


# --- what must not happen ---


@pytest.mark.parametrize(
    ("files", "code"),
    [
        ({"../sentinel.txt": b"overwritten"}, "unsafe_path"),
        ({"..\\sentinel.txt": b"overwritten"}, "unsafe_path"),
        ({"C:\\evil.txt": b"overwritten"}, "unsafe_path"),
        ({"dir/CON.txt": b"x"}, "unsafe_path"),
        ({"a.txt:stream": b"x"}, "unsafe_path"),
        ({"A.txt": b"1", "a.TXT": b"2"}, "duplicate_path"),
    ],
)
def test_hostile_archives_write_nothing(
    api: TestClient,
    rig: Rig,
    archives: Path,
    unpack_root: Path,
    files: dict[str, bytes],
    code: str,
) -> None:
    sentinel = unpack_root.parent / "sentinel.txt"
    sentinel.write_text("untouched", encoding="utf-8")
    serve(rig, samples.zip_with(archives / "a.zip", files))
    work = first_work(api)
    download_only(api, work["id"])
    done = unpack(api, work["id"])
    assert done["state"] == "failed"
    assert done["code"] == code
    assert done["message"]
    assert list(unpack_root.iterdir()) == []
    assert sentinel.read_text(encoding="utf-8") == "untouched"
    assert len(final_files(rig)) == 1  # The download is still there.


def test_existing_folders_are_never_merged_or_replaced(
    api: TestClient, rig: Rig, archives: Path, unpack_root: Path
) -> None:
    work = first_work(api)
    existing = unpack_root / work["sourceId"]
    existing.mkdir()
    save = existing / "セーブ.dat"
    save.write_bytes(b"the user's save")
    serve(rig, samples.zip_with(archives / "a.zip", {"セーブ.dat": b"from the archive"}))
    download_only(api, work["id"])
    done = unpack(api, work["id"])
    assert done["state"] == "done"
    assert save.read_bytes() == b"the user's save"
    assert tree(existing) == ["セーブ.dat"]
    second = unpack_root / f"{work['sourceId']} (2)"
    assert done["location"] == str(second)
    assert (second / "セーブ.dat").read_bytes() == b"from the archive"


def test_asking_again_makes_a_new_folder(
    api: TestClient, rig: Rig, archives: Path, unpack_root: Path
) -> None:
    serve(rig, samples.zip_with(archives / "a.zip", {"a.txt": b"x"}))
    work = first_work(api)
    download_only(api, work["id"])
    first = unpack(api, work["id"])
    # Asking without saying "again" is the same request.
    api.post(BASE, json={"workId": work["id"]})
    assert settled(api, work["id"])["id"] == first["id"]
    assert len(list(unpack_root.iterdir())) == 1
    response = api.post(BASE, json={"workId": work["id"], "again": True})
    assert response.status_code == 202
    assert settled(api, work["id"])["id"] != first["id"]
    assert len(list(unpack_root.iterdir())) == 2


def test_requests_cannot_name_a_file_or_folder(api: TestClient, tmp_path: Path) -> None:
    work = first_work(api)
    for extra in ({"path": str(tmp_path)}, {"file": "C:\\a.zip"}, {"target": str(tmp_path)}):
        assert api.post(BASE, json={"workId": work["id"], **extra}).status_code == 422


def test_nothing_downloaded_means_nothing_to_unpack(api: TestClient) -> None:
    response = api.post(BASE, json={"workId": first_work(api)["id"]})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_download"


def test_no_folder_is_refused_before_a_long_download(
    settings: Settings, rig: Rig, archives: Path
) -> None:
    with client_for(settings) as client:
        prepare(client, rig)
        serve(rig, samples.zip_with(archives / "a.zip", {"a.txt": b"x"}))
        work = first_work(client)
        response = client.post("/api/v1/downloads", json={"workId": work["id"], "extract": True})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "folder_not_set"
        assert client.get("/api/v1/downloads").json()["tasks"] == []


# --- the input ---


@pytest.mark.parametrize("change", ["replace", "delete"])
def test_a_changed_input_is_refused(
    api: TestClient, rig: Rig, archives: Path, unpack_root: Path, change: str
) -> None:
    serve(rig, samples.zip_with(archives / "a.zip", {"a.txt": b"original"}))
    work = first_work(api)
    download_only(api, work["id"])
    file = final_files(rig)[0]
    if change == "delete":
        file.unlink()
    else:
        samples.zip_with(file, {"a.txt": b"swapped!"})
    done = unpack(api, work["id"])
    assert done["state"] == "failed"
    assert done["code"] == "input_changed"
    assert list(unpack_root.iterdir()) == []


def test_a_task_of_another_account_is_refused(api: TestClient, rig: Rig, archives: Path) -> None:
    from app.db.schema import source_accounts

    serve(rig, samples.zip_with(archives / "a.zip", {"a.txt": b"x"}))
    work = first_work(api)
    download_only(api, work["id"])
    with engine_of(api).begin() as connection:
        connection.execute(update(source_accounts).values(account_fingerprint="someone-else"))
    response = api.post(BASE, json={"workId": work["id"]})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "account_changed"


def test_a_lapsed_session_does_not_stop_local_unpacking(
    api: TestClient, rig: Rig, archives: Path
) -> None:
    serve(rig, samples.zip_with(archives / "a.zip", {"a.txt": b"x"}))
    work = first_work(api)
    download_only(api, work["id"])
    api.post("/api/v1/sources/dlsite/disconnect")
    assert unpack(api, work["id"])["state"] == "done"


@pytest.mark.parametrize("visibility", ["hidden", "private", "quarantined"])
def test_works_outside_ordinary_views_stay_out(
    api: TestClient, rig: Rig, archives: Path, visibility: str
) -> None:
    serve(rig, samples.zip_with(archives / "a.zip", {"a.txt": b"x"}))
    work = first_work(api)
    download_only(api, work["id"])
    done = unpack(api, work["id"])
    with engine_of(api).begin() as connection:
        connection.execute(
            update(personal_records)
            .where(personal_records.c.work_id == work["id"])
            .values(visibility=visibility)
        )
    assert api.post(BASE, json={"workId": work["id"]}).status_code == 404
    listed = api.get(BASE).json()
    assert listed == {"tasks": [], "activeCount": 0}
    assert api.post(f"{BASE}/{done['id']}/open-folder").status_code == 404


# --- failure, retry, cancel ---


def test_a_failed_unpacking_retries_without_downloading(
    api: TestClient, rig: Rig, archives: Path, unpack_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    serve(rig, samples.zip_with(archives / "a.zip", {"a.txt": b"x"}))
    work = first_work(api)
    download_only(api, work["id"])
    server = api.app.state.service.downloads._on_shutdown.__self__  # type: ignore[attr-defined]
    fetched = len(server.log.file_requests())

    def broken(*_args: Any) -> None:
        raise ArchiveProblem("extract_failed")

    monkeypatch.setattr(extractions_module, "extract_zip", broken)
    done = unpack(api, work["id"])
    assert done["state"] == "failed"
    assert done["code"] == "extract_failed"
    assert done["canRetry"] is True
    assert done["location"] is None
    assert list(unpack_root.iterdir()) == []
    monkeypatch.undo()

    assert api.post(f"{BASE}/{done['id']}/retry").status_code == 200
    again = settled(api, work["id"])
    assert again["state"] == "done"
    assert len(server.log.file_requests()) == fetched
    assert len(final_files(rig)) == 1


def test_cancel_stops_cleans_up_and_keeps_the_download(
    api: TestClient, rig: Rig, archives: Path, unpack_root: Path
) -> None:
    archive = samples.zip_with(
        archives / "big.zip", {f"{i}.bin": bytes(range(256)) * 80_000 for i in range(40)}
    )
    serve(rig, archive)
    work = first_work(api)
    download_only(api, work["id"])
    api.post(BASE, json={"workId": work["id"]})
    while True:
        task = extraction_of(api, work["id"])
        assert task is not None
        if task["state"] in ("extracting", "done"):
            break
        time.sleep(0.005)
    began = time.monotonic()
    api.post(f"{BASE}/{task['id']}/cancel")
    done = settled(api, work["id"])
    if done["state"] == "done":
        pytest.skip("finished before the cancel arrived")
    assert done["state"] == "cancelled"
    assert time.monotonic() - began < 5
    assert list(unpack_root.iterdir()) == []
    assert len(final_files(rig)) == 1
    assert api.post(f"{BASE}/{task['id']}/cancel").json()["state"] == "cancelled"


def test_cancelling_something_finished_leaves_it_finished(
    api: TestClient, rig: Rig, archives: Path, unpack_root: Path
) -> None:
    serve(rig, samples.zip_with(archives / "a.zip", {"a.txt": b"x"}))
    work = first_work(api)
    download_only(api, work["id"])
    done = unpack(api, work["id"])
    assert api.post(f"{BASE}/{done['id']}/cancel").json()["state"] == "done"
    assert len(list(unpack_root.iterdir())) == 1


def test_a_late_attempt_cannot_change_a_newer_one(
    api: TestClient, rig: Rig, archives: Path
) -> None:
    serve(rig, samples.zip_with(archives / "a.zip", {"a.txt": b"x"}))
    work = first_work(api)
    download_only(api, work["id"])
    done = unpack(api, work["id"])
    service = api.app.state.service.extractions  # type: ignore[attr-defined]
    assert service._write(done["id"], 0, state="failed", code="unexpected") is False
    assert extraction_of(api, work["id"])["state"] == "done"  # type: ignore[index]


def test_a_removed_result_is_reported(
    api: TestClient, rig: Rig, archives: Path, unpack_root: Path
) -> None:
    serve(rig, samples.zip_with(archives / "a.zip", {"a.txt": b"x"}))
    work = first_work(api)
    download_only(api, work["id"])
    done = unpack(api, work["id"])
    shutil.rmtree(unpack_root / work["sourceId"])
    after = extraction_of(api, work["id"])
    assert after is not None
    assert after["state"] == "done"
    assert after["resultMissing"] is True
    assert api.post(f"{BASE}/{done['id']}/open-folder").status_code == 409


def test_not_enough_space_stops_first(
    api: TestClient, rig: Rig, archives: Path, unpack_root: Path
) -> None:
    serve(rig, samples.zip_with(archives / "a.zip", {"a.bin": b"x" * 10_000}))
    work = first_work(api)
    download_only(api, work["id"])
    api.app.state.service.extractions._free_space = lambda _path: 10  # type: ignore[attr-defined]
    done = unpack(api, work["id"])
    assert done["code"] == "disk_full"
    assert list(unpack_root.iterdir()) == []


def test_a_missing_tool_is_explained(
    api: TestClient, rig: Rig, archives: Path, unpack_root: Path
) -> None:
    serve(rig, samples.rar(archives / "a.rar", {"a.txt": b"x"}))
    work = first_work(api)
    download_only(api, work["id"])
    api.app.state.service.extractions._find_tool = lambda: None  # type: ignore[attr-defined]
    done = unpack(api, work["id"])
    assert done["state"] == "failed"
    assert done["code"] == "tool_missing"
    assert "7-Zip" in done["message"]


# --- restarts ---


def _crash(client: TestClient, task_id: str, **values: Any) -> None:
    with engine_of(client).begin() as connection:
        connection.execute(
            update(extract_tasks).where(extract_tasks.c.id == task_id).values(**values)
        )


def _prepared(client: TestClient, rig: Rig, archives: Path, unpack_root: Path) -> dict[str, Any]:
    prepare(client, rig)
    client.put("/api/v1/settings/folders/extract", json={"path": str(unpack_root)})
    serve(rig, samples.zip_with(archives / "a.zip", {"a.txt": b"content"}))
    work = first_work(client)
    download_only(client, work["id"])
    return unpack(client, work["id"])


def test_crash_after_the_rename_is_recognized_as_finished(
    settings: Settings, rig: Rig, archives: Path, unpack_root: Path
) -> None:
    with client_for(settings) as client:
        done = _prepared(client, rig, archives, unpack_root)
        _crash(client, done["id"], state="committing", active_key="x", finished_at=None)
    with client_for(settings) as client:
        tasks = client.get(BASE).json()["tasks"]
        assert tasks[0]["state"] == "done"
        assert tasks[0]["location"] == done["location"]


def test_a_folder_that_does_not_match_is_not_claimed(
    settings: Settings, rig: Rig, archives: Path, unpack_root: Path
) -> None:
    with client_for(settings) as client:
        done = _prepared(client, rig, archives, unpack_root)
        (Path(done["location"]) / "someone else's file.txt").write_bytes(b"not ours")
        _crash(client, done["id"], state="committing", active_key="x", finished_at=None)
    with client_for(settings) as client:
        assert client.get(BASE).json()["tasks"][0]["state"] == "interrupted"
    assert (Path(done["location"]) / "someone else's file.txt").exists()


def test_crash_while_unpacking_clears_only_its_own_folder(
    settings: Settings, rig: Rig, archives: Path, unpack_root: Path
) -> None:
    other = unpack_root / ".atlas-extract-not-this-task"
    with client_for(settings) as client:
        done = _prepared(client, rig, archives, unpack_root)
        with engine_of(client).connect() as connection:
            task_id = connection.execute(select(extract_tasks.c.id)).scalar_one()
        staging = unpack_root / f".atlas-extract-{task_id}"
        staging.mkdir()
        (staging / "half.bin").write_bytes(b"half")
        other.mkdir()
        _crash(client, done["id"], state="extracting", active_key="x", finished_at=None)
    with client_for(settings) as client:
        client.headers.update(write_headers(client))
        task = client.get(BASE).json()["tasks"][0]
        assert task["state"] == "interrupted"
        assert task["canRetry"] is True
    assert not staging.exists()
    assert other.is_dir()  # Not recorded as this task's, so not touched.
    assert Path(done["location"]).is_dir()


def test_a_restart_starts_nothing_by_itself(
    settings: Settings, rig: Rig, archives: Path, unpack_root: Path
) -> None:
    with client_for(settings) as client:
        done = _prepared(client, rig, archives, unpack_root)
        _crash(client, done["id"], state="queued", active_key="x", finished_at=None)
    with client_for(settings) as client:
        time.sleep(0.2)
        assert client.get(BASE).json()["tasks"][0]["state"] == "interrupted"


# --- nothing leaks ---


def test_answers_hold_no_input_paths_and_no_tool_details(
    api: TestClient, rig: Rig, archives: Path
) -> None:
    serve(rig, samples.zip_with(archives / "a.zip", {"../evil.txt": b"x"}))
    work = first_work(api)
    download_only(api, work["id"])
    unpack(api, work["id"])
    text = api.get(BASE).text
    assert str(rig.library) not in text
    assert "7z.exe" not in text
    assert "evil.txt" not in text


def test_every_work_gets_its_own_folder(
    api: TestClient, rig: Rig, archives: Path, unpack_root: Path
) -> None:
    serve(rig, samples.zip_with(archives / "a.zip", {"a.txt": b"x"}))
    works = work_ids(api)[:2]
    for work in works:
        download_only(api, work["id"])
        assert unpack(api, work["id"])["state"] == "done"
    assert sorted(path.name for path in unpack_root.iterdir()) == sorted(
        work["sourceId"] for work in works
    )
