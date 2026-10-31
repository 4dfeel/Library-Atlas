"""Download and unpack through the whole backend: the real API and queues, real sockets, real
files and the real 7-Zip. The archives are synthetic and the platform is pretend."""

import shutil
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.adapters.system.archives import ArchiveProblem, find_seven_zip
from app.core.config import Settings
from app.db.schema import extract_tasks, personal_records, works
from app.repositories import app_settings
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
def unpack_root(rig: Rig) -> Path:
    return rig.works


@pytest.fixture
def api(settings: Settings, rig: Rig, unpack_root: Path) -> Iterator[TestClient]:
    with client_for(settings) as client:
        prepare(client, rig)
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


def download_only_again(client: TestClient, work_id: str) -> None:
    for task in start(client, work_id, again=True):
        assert ended(client, task["id"])["state"] == "done"


def download_and_unpack_again(client: TestClient, work_id: str) -> dict[str, Any]:
    """The archive went away after the first time, so unpacking again means fetching it again."""
    before = extraction_of(client, work_id)
    assert before is not None
    start(client, work_id, again=True, extract=True)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        task = extraction_of(client, work_id)
        if task and task["id"] != before["id"] and task["state"] not in ACTIVE:
            return task
        time.sleep(0.02)
    raise AssertionError("timed out")


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
    # Filed as the user files works: type, then maker, then title.
    result = Path(done["location"])
    assert result.relative_to(unpack_root).parts[1:] == ("虚构社团", work["title"])
    assert tree(result) == ["说明.txt".replace("说", "説"), "音声/01 はじめに.wav"]
    assert (result / "音声" / "01 はじめに.wav").read_bytes() == b"a" * 1000
    # The archive is gone once the work is in place: no second copy, as the user asked.
    assert final_files(rig) == []
    assert len(list(unpack_root.iterdir())) == 1  # Nothing temporary was left beside it.


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
    done = unpack(api, work["id"])
    assert done["state"] == "done"
    assert (Path(done["location"]) / "a.txt").read_bytes() == b"x"


def test_one_click_on_a_finished_download_does_not_download_again(
    api: TestClient, rig: Rig, archives: Path
) -> None:
    serve(rig, samples.zip_with(archives / "a.zip", {"a.txt": b"x"}))
    work = first_work(api)
    download_only(api, work["id"])
    files_before = final_files(rig)
    assert len(files_before) == 1
    server = api.app.state.service.downloads._on_shutdown.__self__  # type: ignore[attr-defined]
    fetched = len(server.log.file_requests())
    start(api, work["id"], extract=True)
    assert settled(api, work["id"])["state"] == "done"
    assert len(server.log.file_requests()) == fetched


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
    assert done["state"] == "done", done["code"]
    assert done["format"] == "rar"
    assert (Path(done["location"]) / "movie.bin").read_bytes() == data


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


def test_a_file_that_is_not_an_archive_is_filed_the_same_way(
    api: TestClient, rig: Rig, unpack_root: Path
) -> None:
    rig.behave(size=2000)  # Made-up bytes with no archive signature.
    work = first_work(api)
    start(api, work["id"], extract=True)
    done = settled(api, work["id"])
    assert done["state"] == "done"
    assert done["format"] == "file"
    result = Path(done["location"])
    assert result.relative_to(unpack_root).parts[1:] == ("虚构社团", work["title"])
    assert (result / f"{work['sourceId']}.zip").stat().st_size == 2000
    assert final_files(rig) == []  # Once in place, no second copy.


def test_a_plain_program_is_filed_and_never_run(
    api: TestClient, rig: Rig, archives: Path, tmp_path: Path
) -> None:
    tool = find_seven_zip()
    if tool is None:
        pytest.skip("needs 7-Zip")
    program = archives / "program.exe"
    shutil.copyfile(tool.executable, program)
    serve(rig, program)
    work = first_work(api)
    start(api, work["id"], extract=True)
    done = settled(api, work["id"])
    assert done["format"] == "file"
    assert Path(done["location"]).is_dir()


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
    api: TestClient, rig: Rig, archives: Path
) -> None:
    serve(rig, samples.zip_with(archives / "a.zip", {"セーブ.dat": b"from the archive"}))
    work = first_work(api)
    download_only(api, work["id"])
    first = Path(unpack(api, work["id"])["location"])
    save = first / "セーブ.dat"
    save.write_bytes(b"the user's save")
    done = download_and_unpack_again(api, work["id"])
    assert done["state"] == "done"
    assert save.read_bytes() == b"the user's save"
    second = Path(done["location"])
    assert second == first.with_name(f"{first.name} (2)")
    assert (second / "セーブ.dat").read_bytes() == b"from the archive"


def test_a_link_along_the_way_cannot_lead_the_result_outside(
    api: TestClient, rig: Rig, archives: Path, unpack_root: Path, tmp_path: Path
) -> None:
    winapi = pytest.importorskip("_winapi")
    serve(rig, samples.zip_with(archives / "a.zip", {"a.txt": b"x"}))
    work = first_work(api)
    download_only(api, work["id"])
    first = Path(unpack(api, work["id"])["location"])
    download_only_again(api, work["id"])
    kind = first.relative_to(unpack_root).parts[0]
    shutil.rmtree(unpack_root / kind)
    outside = tmp_path / "outside"
    outside.mkdir()
    winapi.CreateJunction(str(outside), str(unpack_root / kind))
    assert api.post(BASE, json={"workId": work["id"], "again": True}).status_code == 202
    done = settled(api, work["id"])
    assert done["state"] == "failed"
    assert done["code"] == "folder_invalid"
    assert not any(path.is_file() for path in outside.rglob("*"))


def test_two_works_with_the_same_title_do_not_mix(
    api: TestClient, rig: Rig, archives: Path
) -> None:
    serve(rig, samples.zip_with(archives / "a.zip", {"a.txt": b"x"}))
    one, two = work_ids(api)[:2]
    with engine_of(api).begin() as connection:
        connection.execute(update(works).values(title="同名作品", kind="game"))
    download_only(api, one["id"])
    download_only(api, two["id"])
    first = Path(unpack(api, one["id"])["location"])
    second = Path(unpack(api, two["id"])["location"])
    assert first != second
    assert first.name == "同名作品"
    assert second.name == "同名作品 (2)"


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
    assert Path(first["location"]).is_dir()
    second = download_and_unpack_again(api, work["id"])
    assert second["id"] != first["id"]
    assert second["location"] != first["location"]
    assert Path(first["location"]).is_dir()
    assert Path(second["location"]).is_dir()


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
        with engine_of(client).begin() as connection:
            app_settings.put(connection, "folder.library", "")
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
    assert final_files(rig) == []


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
    assert Path(done["location"]).is_dir()


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
    shutil.rmtree(done["location"])
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


# --- the archive afterwards ---


def test_a_failed_unpacking_keeps_the_archive(api: TestClient, rig: Rig, archives: Path) -> None:
    serve(rig, samples.zip_with(archives / "a.zip", {"../evil.txt": b"x"}))
    work = first_work(api)
    start(api, work["id"], extract=True)
    assert settled(api, work["id"])["state"] == "failed"
    assert len(final_files(rig)) == 1


def test_download_only_keeps_the_archive(api: TestClient, rig: Rig, archives: Path) -> None:
    serve(rig, samples.zip_with(archives / "a.zip", {"a.txt": b"x"}))
    download_only(api, first_work(api)["id"])
    assert len(final_files(rig)) == 1


def test_only_its_own_files_go_with_the_archive(api: TestClient, rig: Rig, archives: Path) -> None:
    serve(rig, samples.zip_with(archives / "a.zip", {"a.txt": b"x"}))
    work = first_work(api)
    download_only(api, work["id"])
    neighbor = rig.library / work["sourceId"] / "the user's note.txt"
    neighbor.write_bytes(b"keep")
    assert unpack(api, work["id"])["state"] == "done"
    assert neighbor.read_bytes() == b"keep"
    assert final_files(rig) == [neighbor]


def test_a_removed_archive_is_not_reported_as_a_lost_file(
    api: TestClient, rig: Rig, archives: Path
) -> None:
    serve(rig, samples.zip_with(archives / "a.zip", {"a.txt": b"x"}))
    work = first_work(api)
    start(api, work["id"], extract=True)
    settled(api, work["id"])
    # Unpacking is reported as done a moment before the archive goes and the folder is recorded.
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        task = api.get("/api/v1/downloads").json()["tasks"][0]
        installed = api.get(f"/api/v1/works/{work['id']}").json()["installed"]
        if task["archiveRemoved"] and installed:
            break
        time.sleep(0.02)
    assert task["archiveRemoved"] is True
    assert task["fileMissing"] is False
    assert installed is True
    # Nothing to unpack from now, and it says so instead of failing halfway.
    response = api.post(BASE, json={"workId": work["id"], "again": True})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_download"


def test_clearing_empties_the_list_and_touches_no_result(
    api: TestClient, rig: Rig, archives: Path
) -> None:
    serve(rig, samples.zip_with(archives / "a.zip", {"a.txt": b"x"}))
    work = first_work(api)
    start(api, work["id"], extract=True)
    done = settled(api, work["id"])
    assert api.post(f"{BASE}/clear").status_code == 200
    assert api.post("/api/v1/downloads/clear").status_code == 200
    assert all(t["dismissed"] for t in api.get(BASE).json()["tasks"])
    assert all(t["dismissed"] for t in api.get("/api/v1/downloads").json()["tasks"])
    assert (Path(done["location"]) / "a.txt").read_bytes() == b"x"


def test_an_update_is_still_noticed_after_clearing(
    api: TestClient, rig: Rig, archives: Path
) -> None:
    serve(rig, samples.zip_with(archives / "a.zip", {"a.txt": b"x"}))
    work = first_work(api)
    start(api, work["id"], extract=True)
    settled(api, work["id"])
    api.post("/api/v1/downloads/clear")
    rig.control["upgrade"] = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    rig.save_control()
    assert api.post("/api/v1/sources/dlsite/sync").status_code == 200
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if api.get("/api/v1/downloads").json()["updates"]:
            break
        time.sleep(0.05)
    assert [item["workId"] for item in api.get("/api/v1/downloads").json()["updates"]] == [
        work["id"]
    ]


def test_a_japanese_rar_reaches_the_folder_with_japanese_names(
    api: TestClient, rig: Rig, archives: Path
) -> None:
    if find_seven_zip() is None:
        pytest.skip("needs 7-Zip")
    archive = samples.rar(archives / "a.rar", {"音声\\表紙.txt": b"hello"}, name_encoding="cp932")
    serve(rig, archive)
    work = first_work(api)
    start(api, work["id"], extract=True)
    done = settled(api, work["id"])
    assert done["state"] == "done", done["code"]
    assert (Path(done["location"]) / "音声" / "表紙.txt").read_bytes() == b"hello"


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


def test_every_work_gets_its_own_folder(api: TestClient, rig: Rig, archives: Path) -> None:
    serve(rig, samples.zip_with(archives / "a.zip", {"a.txt": b"x"}))
    locations = set()
    for work in work_ids(api)[:2]:
        download_only(api, work["id"])
        done = unpack(api, work["id"])
        assert done["state"] == "done"
        assert Path(done["location"]).name == work["title"]
        locations.add(done["location"])
    assert len(locations) == 2
