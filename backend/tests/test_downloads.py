"""Downloads through the whole backend: the real API and queue, real sockets, real files. Only
the platform on the other end of the socket is pretend, so these prove Atlas's handling of
each answer, never how DLsite really behaves."""

import hashlib
import json
import logging
import os
import subprocess
import sys
import threading
import time
import tracemalloc
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.adapters.dlsite.downloads import (
    LoginRequired,
    PlatformDownloadClient,
    UnexpectedHost,
    Validators,
    looks_like_page,
    platform_url_allowed,
)
from app.adapters.dlsite.session import SessionCookie
from app.core.config import Settings
from app.db.schema import download_tasks, personal_records, source_accounts, works
from app.domain.download_names import (
    name_from_disposition,
    name_from_path,
    numbered,
    safe_file_name,
)
from app.services import downloads as downloads_module
from app.services.downloads import MAX_RUNNING
from app.testing.fake_dlsite import CONTROL_FILE
from app.testing.fake_download_server import FakeDownloadServer, file_bytes
from tests.conftest import client_for, write_headers

BASE = "/api/v1/downloads"
ACTIVE = ("queued", "resolving", "downloading", "verifying")
ENDED = ("done", "failed", "cancelled", "reauth_required", "interrupted", "paused")
# Larger than one read, so a transfer that stops midway has really written something.
SIZE = 2_000_000


class Rig:
    def __init__(self, settings: Settings, tmp_path: Path) -> None:
        self.settings = settings
        self.library = tmp_path / "作品 フォルダ"
        self.library.mkdir()
        self.control: dict[str, Any] = {"size": 6}
        self.save_control()

    def save_control(self) -> None:
        path = self.settings.data_dir / CONTROL_FILE
        path.write_text(json.dumps(self.control), encoding="utf-8")

    def behave(self, **download: Any) -> None:
        self.control["download"] = download
        self.save_control()


def queue_of(client: TestClient) -> Any:
    return client.app.state.service.downloads  # type: ignore[attr-defined]


def engine_of(client: TestClient) -> Any:
    return client.app.state.service.engine  # type: ignore[attr-defined]


@pytest.fixture
def rig(settings: Settings, tmp_path: Path) -> Rig:
    return Rig(settings, tmp_path)


def wait_for(check: Any, seconds: float = 15.0) -> Any:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("timed out")


def prepare(client: TestClient, rig: Rig) -> None:
    client.headers.update(write_headers(client))
    login = client.post(
        "/api/v1/sources/dlsite/login", json={"loginId": "ok", "password": "not-a-real-password"}
    )
    assert login.status_code == 200
    wait_for(lambda: client.get("/api/v1/sources/dlsite/connection").json()["state"] == "connected")
    assert client.post("/api/v1/sources/dlsite/sync").status_code == 200
    wait_for(
        lambda: (client.get("/api/v1/sources/dlsite/sync").json().get("job") or {}).get("state")
        == "succeeded"
    )
    assert (
        client.put("/api/v1/settings/folders/library", json={"path": str(rig.library)}).status_code
        == 200
    )


@pytest.fixture
def api(settings: Settings, rig: Rig) -> Iterator[TestClient]:
    with client_for(settings) as client:
        prepare(client, rig)
        yield client


def work_ids(client: TestClient) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = client.get(
        "/api/v1/works", params={"limit": 100, "search": "合成作品"}
    ).json()["items"]
    return items


def first_work(client: TestClient) -> dict[str, Any]:
    return work_ids(client)[0]


def start(client: TestClient, work_id: str, **body: Any) -> list[dict[str, Any]]:
    response = client.post(BASE, json={"workId": work_id, **body})
    assert response.status_code == 202, response.text
    tasks: list[dict[str, Any]] = response.json()["tasks"]
    return tasks


def task_by_id(client: TestClient, task_id: str) -> dict[str, Any]:
    return next(task for task in client.get(BASE).json()["tasks"] if task["id"] == task_id)


def ended(client: TestClient, task_id: str, seconds: float = 20.0) -> dict[str, Any]:
    def check() -> dict[str, Any] | None:
        task = task_by_id(client, task_id)
        return task if task["state"] in ENDED else None

    result: dict[str, Any] = wait_for(check, seconds)
    return result


def run_one(client: TestClient, **body: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    work = first_work(client)
    task = start(client, work["id"], **body)[0]
    return work, ended(client, task["id"])


def parts_left(settings: Settings) -> list[Path]:
    cache = settings.data_dir / "download-cache"
    return list(cache.glob("*.part")) if cache.exists() else []


def final_files(rig: Rig) -> list[Path]:
    return sorted(path for path in rig.library.rglob("*") if path.is_file())


# --- names ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("作品 ファイル.zip", "作品 ファイル.zip"),
        ("..\\..\\windows\\evil.exe", "evil.exe"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\a.zip", "a.zip"),
        ("CON.zip", "_CON.zip"),
        ("lpt1", "_lpt1"),
        ("a<b>c:d.zip", "a_b_c_d.zip"),
        ("name. . ", "name"),
        ("...", "fallback"),
        ("", "fallback"),
        (None, "fallback"),
        ("\x00\x01", "fallback"),
    ],
)
def test_names_stay_one_safe_segment(raw: str | None, expected: str) -> None:
    assert safe_file_name(raw, "fallback") == expected


def test_long_names_keep_their_extension_and_whole_characters() -> None:
    name = safe_file_name("長" * 300 + ".part1.rar", "x")
    assert name.endswith(".rar")
    assert len(name.encode()) <= 200
    name.encode().decode()


def test_names_come_from_headers_and_addresses() -> None:
    assert name_from_disposition('attachment; filename="a b.zip"') == "a b.zip"
    assert name_from_disposition("attachment; filename=a.zip") == "a.zip"
    assert name_from_disposition("attachment; filename*=UTF-8''%E4%BD%9C.zip") == "作.zip"
    assert name_from_disposition("attachment") is None
    assert name_from_path("/home/download/=/file/%E4%BD%9C.zip/product_id/X.html") == "作.zip"
    assert name_from_path("/home/download") is None
    assert numbered("a.zip", 2) == "a (2).zip"
    assert numbered("noext", 3) == "noext (3)"


# --- address rules ---


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://www.dlsite.com/home/download", True),
        ("https://download.dlsite.com/x", True),
        ("https://dlsite.com/x", True),
        ("http://www.dlsite.com/x", False),
        ("https://www.dlsite.com:8443/x", False),
        ("https://dlsite.com.evil.example/x", False),
        ("https://evildlsite.com/x", False),
        ("https://127.0.0.1/x", False),
        ("https://localhost/x", False),
        ("file:///C:/Windows/win.ini", False),
    ],
)
def test_only_platform_addresses_are_allowed(url: str, allowed: bool) -> None:
    assert platform_url_allowed(httpx.URL(url)) is allowed


@pytest.mark.parametrize(
    ("first", "page"),
    [
        (b"<!DOCTYPE html><html>", True),
        (b"\r\n  <html lang=ja>", True),
        (b'{"error":"denied"}', True),
        (b"PK\x03\x04archive", False),
        (b"Rar!\x1a\x07", False),
        (b"MZ\x90\x00", False),
    ],
)
def test_pages_are_recognized_whatever_they_are_labelled(first: bytes, page: bool) -> None:
    assert looks_like_page(first) is page


def test_session_reaches_platform_hosts_and_nothing_else() -> None:
    """A redirect to another host gets no cookie, because it gets no request at all."""
    behavior: dict[str, Any] = {}
    allowed = FakeDownloadServer(lambda: behavior)
    other = FakeDownloadServer(lambda: {})
    try:
        cookie = SessionCookie("sid", "secret-session-value", "127.0.0.1")
        client = PlatformDownloadClient(
            [cookie], entry_url=allowed.entry_url, allows=lambda url: url.port == allowed.port
        )
        plan = client.plan("RJ1")
        assert allowed.log.requests[0]["cookie"] == "sid=secret-session-value"
        opened = client.open(plan.files[0].url, 0, Validators())
        opened.close()
        client.close()

        # Now the entry points at the other server.
        allowed.behavior = lambda: {"mode": "normal"}
        client = PlatformDownloadClient(
            [cookie],
            entry_url=f"{other.origin}/api/v3/download",
            allows=lambda url: url.port == allowed.port,
        )
        with pytest.raises(UnexpectedHost):
            client.plan("RJ1")
        client.close()
        assert other.log.requests == []
    finally:
        allowed.close()
        other.close()


def test_a_login_redirect_is_not_mistaken_for_a_file() -> None:
    server = FakeDownloadServer(lambda: {"mode": "to_login"})
    try:
        client = PlatformDownloadClient(
            [], entry_url=server.entry_url, allows=lambda url: url.host == "127.0.0.1"
        )
        with pytest.raises(LoginRequired):
            client.plan("RJ1")
        client.close()
    finally:
        server.close()


# --- the whole way ---


def test_a_file_arrives_whole_in_the_chosen_folder(api: TestClient, rig: Rig) -> None:
    rig.behave(size=SIZE)
    work, task = run_one(api)
    assert task["state"] == "done", task
    assert task["bytesDone"] == task["bytesTotal"] == SIZE
    assert task["integrity"] == "length"
    files = final_files(rig)
    assert len(files) == 1
    source_id = work["sourceId"]
    assert files[0].parent == rig.library / source_id
    assert files[0].name == f"{source_id}.zip"
    assert files[0].read_bytes() == file_bytes(source_id, 0, SIZE)
    assert parts_left(rig.settings) == []
    assert task["location"] == str(rig.library / source_id)
    # Downloaded, and nothing more than that.
    assert api.get(f"/api/v1/works/{work['id']}").json()["installed"] is True
    with engine_of(api).connect() as connection:
        row = connection.execute(select(download_tasks)).first()
    assert row.sha256 == hashlib.sha256(files[0].read_bytes()).hexdigest()


def test_nothing_is_read_or_written_before_the_user_asks(api: TestClient, rig: Rig) -> None:
    assert api.get(BASE).json() == {"tasks": [], "activeCount": 0}
    api.get("/api/v1/works", params={"limit": 100})
    assert final_files(rig) == []


def test_plan_describes_without_writing(api: TestClient, rig: Rig) -> None:
    work = first_work(api)
    rig.behave(parts=3)
    plan = api.post(f"/api/v1/works/{work['id']}/download-plan").json()
    assert plan["kind"] == "split"
    assert plan["parts"] == [1, 2, 3]
    assert plan["folder"]["status"] == "ok"
    assert plan["freeBytes"] > 0
    rig.behave()
    plan = api.post(f"/api/v1/works/{work['id']}/download-plan").json()
    assert plan["kind"] == "direct"
    assert plan["parts"] == []
    assert api.get(BASE).json()["tasks"] == []
    assert final_files(rig) == []


def test_split_parts_are_tracked_separately_and_only_those_chosen(
    api: TestClient, rig: Rig
) -> None:
    rig.behave(parts=3, size=50_000)
    work = first_work(api)
    tasks = start(api, work["id"], parts=[1, 3])
    assert sorted(task["part"] for task in tasks) == [1, 3]
    assert {task["partCount"] for task in tasks} == {3}
    for task in tasks:
        assert ended(api, task["id"])["state"] == "done"
    names = [path.name for path in final_files(rig)]
    source_id = work["sourceId"]
    assert names == [f"{source_id}.part1.rar", f"{source_id}.part3.rar"]
    assert (rig.library / source_id / names[1]).read_bytes() == file_bytes(source_id, 3, 50_000)


def test_a_part_the_platform_does_not_offer_is_refused(api: TestClient, rig: Rig) -> None:
    rig.behave(parts=2)
    response = api.post(BASE, json={"workId": first_work(api)["id"], "parts": [9]})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "file_changed"


def test_serial_works_are_reported_not_attempted(api: TestClient, rig: Rig) -> None:
    rig.behave(mode="serial")
    work = first_work(api)
    assert api.post(f"/api/v1/works/{work['id']}/download-plan").json()["kind"] == "serial"
    response = api.post(BASE, json={"workId": work["id"]})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "download_serial"
    assert api.get(BASE).json()["tasks"] == []


# --- wrong answers must not become files ---


@pytest.mark.parametrize(
    ("mode", "code"),
    [
        ("login_page", "not_a_file"),
        ("disguised_page", "not_a_file"),
        ("json_error", "not_a_file"),
        ("gone", "file_gone"),
        ("challenge", "challenged"),
        ("empty", "empty_file"),
    ],
)
def test_answers_that_are_not_the_file_are_never_saved(
    api: TestClient, rig: Rig, mode: str, code: str
) -> None:
    rig.behave(mode=mode)
    _work, task = run_one(api)
    assert task["state"] == "failed"
    assert task["code"] == code
    assert task["message"]
    assert final_files(rig) == []
    assert parts_left(rig.settings) == []


def test_a_refused_file_gets_one_fresh_address_then_stops(api: TestClient, rig: Rig) -> None:
    rig.behave(mode="forbidden")
    _work, task = run_one(api)
    assert task["state"] == "failed"
    assert task["code"] == "no_permission"
    assert task["canRetry"] is True
    # Refused does not mean signed out.
    assert api.get("/api/v1/sources/dlsite/connection").json()["state"] == "connected"


def test_an_expired_session_asks_for_login_and_keeps_the_rest(api: TestClient, rig: Rig) -> None:
    rig.behave(mode="expired")
    work = first_work(api)
    response = api.post(BASE, json={"workId": work["id"]})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "session_expired"
    assert api.get("/api/v1/sources/dlsite/connection").json()["state"] == "reauth_required"
    assert first_work(api)["id"] == work["id"]


@pytest.mark.parametrize(
    ("mode", "code"),
    [("off_platform", "unexpected_host"), ("unknown_route", "response_changed")],
)
def test_unknown_destinations_stop_before_anything_is_created(
    api: TestClient, rig: Rig, mode: str, code: str
) -> None:
    rig.behave(mode=mode)
    response = api.post(BASE, json={"workId": first_work(api)["id"]})
    assert response.json()["error"]["code"] == code
    assert api.get(BASE).json()["tasks"] == []


def test_a_login_redirect_is_not_reported_as_an_expired_session(api: TestClient, rig: Rig) -> None:
    rig.behave(mode="to_login")
    response = api.post(BASE, json={"workId": first_work(api)["id"]})
    assert response.json()["error"]["code"] == "login_required"
    assert api.get("/api/v1/sources/dlsite/connection").json()["state"] == "connected"


# --- trouble on the way, and resuming ---


def test_rate_limits_are_retried_a_limited_number_of_times(api: TestClient, rig: Rig) -> None:
    rig.behave(mode="limited")
    _work, task = run_one(api)
    assert task["state"] == "failed"
    assert task["code"] == "platform_unavailable"
    assert task["canRetry"] is True


def test_a_passing_failure_is_retried_by_itself(api: TestClient, rig: Rig) -> None:
    rig.behave(mode="flaky", fail_times=1)
    _work, task = run_one(api)
    assert task["state"] == "done"


def test_a_broken_connection_resumes_from_where_it_stopped(api: TestClient, rig: Rig) -> None:
    rig.behave(mode="truncate_once", size=SIZE)
    work, task = run_one(api)
    assert task["state"] == "done", task
    assert final_files(rig)[0].read_bytes() == file_bytes(work["sourceId"], 0, SIZE)


def _file_requests(api: TestClient) -> list[dict[str, Any]]:
    closure = queue_of(api)._on_shutdown.__self__
    requests: list[dict[str, Any]] = closure.log.file_requests()
    return requests


def test_resume_asks_for_the_rest_and_proves_it_is_the_same_file(api: TestClient, rig: Rig) -> None:
    rig.behave(mode="truncate_once", size=SIZE)
    run_one(api)
    requests = _file_requests(api)
    assert len(requests) == 2
    assert requests[0]["range"] is None
    assert requests[1]["range"] is not None
    assert requests[1]["if_range"] == '"v1"'


def _interrupted_part(api: TestClient, rig: Rig, mode: str, size: int = SIZE) -> dict[str, Any]:
    """Leaves a task paused with half a file, then sets how the server answers next."""
    rig.behave(mode="slow", size=size, delay=0.02)
    work = first_work(api)
    task = start(api, work["id"])[0]
    wait_for(lambda: task_by_id(api, task["id"])["state"] == "downloading")
    time.sleep(0.15)
    api.post(f"{BASE}/{task['id']}/pause")
    assert ended(api, task["id"])["state"] == "paused"
    rig.behave(mode=mode, size=size)
    return {"work": work, "task": task}


@pytest.mark.parametrize("mode", ["ignore_range", "bad_offset", "range_416"])
def test_resume_starts_over_when_the_server_will_not_honor_it(
    api: TestClient, rig: Rig, mode: str
) -> None:
    held = _interrupted_part(api, rig, mode)
    api.post(f"{BASE}/{held['task']['id']}/retry")
    done = ended(api, held["task"]["id"])
    assert done["state"] == "done", done
    source_id = held["work"]["sourceId"]
    assert final_files(rig)[0].read_bytes() == file_bytes(source_id, 0, SIZE)


def test_resume_uses_range_after_a_pause(api: TestClient, rig: Rig) -> None:
    held = _interrupted_part(api, rig, "normal")
    task = task_by_id(api, held["task"]["id"])
    assert task["canResume"] is True
    assert 0 < task["bytesDone"] < SIZE
    api.post(f"{BASE}/{held['task']['id']}/retry")
    assert ended(api, held["task"]["id"])["state"] == "done"
    assert _file_requests(api)[-1]["range"] == f"bytes={task['bytesDone']}-"
    source_id = held["work"]["sourceId"]
    assert final_files(rig)[0].read_bytes() == file_bytes(source_id, 0, SIZE)


def test_a_file_that_changed_is_fetched_again_not_spliced(api: TestClient, rig: Rig) -> None:
    """The first response breaks halfway; the second has a new identity."""
    rig.behave(mode="changed_etag", size=SIZE)
    work, task = run_one(api)
    assert task["state"] == "done", task
    assert final_files(rig)[0].read_bytes() == file_bytes(work["sourceId"], 0, SIZE)
    requests = _file_requests(api)
    assert requests[1]["if_range"] == '"v1"'


def test_a_weak_identity_is_not_used_to_resume(api: TestClient, rig: Rig) -> None:
    held = _interrupted_part(api, rig, "weak_etag")
    api.post(f"{BASE}/{held['task']['id']}/retry")
    assert ended(api, held["task"]["id"])["state"] == "done"
    assert final_files(rig)[0].stat().st_size == SIZE


def test_unknown_length_finishes_with_limited_assurance_said_plainly(
    api: TestClient, rig: Rig
) -> None:
    rig.behave(mode="no_length", size=SIZE)
    work, task = run_one(api)
    assert task["state"] == "done", task
    assert task["bytesTotal"] is None
    assert task["integrity"] == "stream_end"
    assert final_files(rig)[0].read_bytes() == file_bytes(work["sourceId"], 0, SIZE)


def test_a_short_file_is_not_called_finished(api: TestClient, rig: Rig) -> None:
    rig.behave(mode="truncate_always", size=SIZE)
    _work, task = run_one(api)
    # Each try gets further by resuming, so this may finish whole; it may never finish short.
    if task["state"] == "done":
        assert final_files(rig)[0].stat().st_size == SIZE
    else:
        assert final_files(rig) == []


def test_a_length_the_body_never_reaches_is_not_finished(api: TestClient, rig: Rig) -> None:
    rig.behave(mode="wrong_length", size=SIZE)
    _work, task = run_one(api)
    assert task["state"] == "failed"
    assert final_files(rig) == []


# --- files and folders ---


def test_existing_files_are_never_replaced(api: TestClient, rig: Rig) -> None:
    work = first_work(api)
    source_id = work["sourceId"]
    folder = rig.library / source_id
    folder.mkdir()
    existing = folder / f"{source_id}.zip"
    existing.write_bytes(b"the user's own file")
    rig.behave(size=SIZE)
    _work, task = run_one(api)
    assert task["state"] == "done"
    assert existing.read_bytes() == b"the user's own file"
    assert task["fileName"] == f"{source_id} (2).zip"
    assert (folder / task["fileName"]).read_bytes() == file_bytes(source_id, 0, SIZE)


def test_hostile_names_stay_inside_the_folder(api: TestClient, rig: Rig) -> None:
    rig.behave(mode="hostile_name", size=1000)
    work, task = run_one(api)
    assert task["state"] == "done"
    assert task["fileName"] == "_CON.zip"
    assert final_files(rig) == [rig.library / work["sourceId"] / "_CON.zip"]


def test_no_folder_chosen_is_refused_before_anything_starts(settings: Settings, rig: Rig) -> None:
    with client_for(settings) as client:
        prepare(client, rig)
        with engine_of(client).begin() as connection:
            from app.repositories import app_settings

            app_settings.put(connection, "folder.library", "")
        response = client.post(BASE, json={"workId": first_work(client)["id"]})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "folder_not_set"


def test_a_missing_folder_is_not_recreated(api: TestClient, rig: Rig) -> None:
    os.rmdir(rig.library)
    response = api.post(BASE, json={"workId": first_work(api)["id"]})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "folder_missing"
    assert not rig.library.exists()


def test_a_folder_lost_during_the_transfer_is_reported(api: TestClient, rig: Rig) -> None:
    rig.behave(mode="slow", size=SIZE, delay=0.02)
    task = start(api, first_work(api)["id"])[0]
    wait_for(lambda: task_by_id(api, task["id"])["state"] == "downloading")
    os.rmdir(rig.library)
    done = ended(api, task["id"])
    assert done["state"] == "failed"
    assert done["code"] == "folder_missing"
    assert not rig.library.exists()


def test_changing_the_folder_does_not_move_a_task(
    api: TestClient, rig: Rig, tmp_path: Path
) -> None:
    other = tmp_path / "another"
    other.mkdir()
    rig.behave(mode="slow", size=SIZE, delay=0.02)
    work = first_work(api)
    task = start(api, work["id"])[0]
    api.put("/api/v1/settings/folders/library", json={"path": str(other)})
    assert ended(api, task["id"])["state"] == "done"
    assert (rig.library / work["sourceId"]).is_dir()
    assert list(other.iterdir()) == []


def test_a_link_out_of_the_folder_is_refused(
    api: TestClient, rig: Rig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    work = first_work(api)
    _winapi = pytest.importorskip("_winapi")
    _winapi.CreateJunction(str(outside), str(rig.library / work["sourceId"]))
    rig.behave(size=1000)
    _work, task = run_one(api)
    assert task["state"] == "failed"
    assert task["code"] == "folder_invalid"
    assert list(outside.iterdir()) == []


def test_files_cross_drives_by_copying_first(
    api: TestClient, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(downloads_module, "_same_drive", lambda _a, _b: False)
    rig.behave(size=SIZE)
    work, task = run_one(api)
    assert task["state"] == "done"
    assert final_files(rig)[0].read_bytes() == file_bytes(work["sourceId"], 0, SIZE)
    assert parts_left(rig.settings) == []
    assert [path.name for path in final_files(rig)] == [f"{work['sourceId']}.zip"]


def test_not_enough_space_stops_before_writing(api: TestClient, rig: Rig) -> None:
    queue_of(api)._free_space = lambda _path: 10
    rig.behave(size=SIZE)
    _work, task = run_one(api)
    assert task["state"] == "failed"
    assert task["code"] == "disk_full"
    assert parts_left(rig.settings) == []


def test_a_write_failure_is_reported(
    api: TestClient, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(_fd: int) -> None:
        raise OSError(5, "refused")

    monkeypatch.setattr(downloads_module.os, "fsync", refuse)
    rig.behave(size=1000)
    _work, task = run_one(api)
    assert task["state"] == "failed"
    assert task["code"] == "write_failed"
    assert final_files(rig) == []


def test_a_disk_filling_up_mid_write_is_reported(
    api: TestClient, rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def full(_fd: int) -> None:
        raise OSError(28, "no space")

    monkeypatch.setattr(downloads_module.os, "fsync", full)
    rig.behave(size=1000)
    _work, task = run_one(api)
    assert task["code"] == "disk_full"
    assert parts_left(rig.settings) == []


# --- the queue ---


def test_asking_twice_is_one_task(api: TestClient, rig: Rig) -> None:
    rig.behave(mode="slow", size=SIZE, delay=0.02)
    work = first_work(api)
    first = start(api, work["id"])
    second = start(api, work["id"])
    assert [task["id"] for task in first] == [task["id"] for task in second]
    assert len(api.get(BASE).json()["tasks"]) == 1
    ended(api, first[0]["id"])


def test_many_clients_at_once_still_make_one_task(api: TestClient, rig: Rig) -> None:
    rig.behave(mode="slow", size=SIZE, delay=0.02)
    work = first_work(api)
    answers: list[int] = []

    def ask() -> None:
        answers.append(api.post(BASE, json={"workId": work["id"]}).status_code)

    threads = [threading.Thread(target=ask) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    tasks = api.get(BASE).json()["tasks"]
    assert len(tasks) == 1
    assert all(status in (202, 409) for status in answers)
    ended(api, tasks[0]["id"])


def test_a_finished_file_is_kept_until_asked_again(api: TestClient, rig: Rig) -> None:
    rig.behave(size=1000)
    work, task = run_one(api)
    assert start(api, work["id"])[0]["id"] == task["id"]
    assert len(final_files(rig)) == 1
    again = start(api, work["id"], again=True)
    ended(api, again[0]["id"])
    assert len(final_files(rig)) == 2


def test_only_a_few_run_at_once(api: TestClient, rig: Rig) -> None:
    rig.behave(mode="slow", size=SIZE, delay=0.02)
    tasks = [start(api, work["id"])[0] for work in work_ids(api)[:4]]
    most = 0
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        states = [task_by_id(api, task["id"])["state"] for task in tasks]
        most = max(most, sum(state in ("resolving", "downloading") for state in states))
        if all(state == "done" for state in states):
            break
        time.sleep(0.02)
    assert all(task_by_id(api, task["id"])["state"] == "done" for task in tasks)
    assert 1 <= most <= MAX_RUNNING


def test_cancel_stops_the_transfer_and_cleans_up_only_its_own_file(
    api: TestClient, rig: Rig
) -> None:
    keep = rig.settings.data_dir / "download-cache" / "not-mine.part"
    keep.parent.mkdir(exist_ok=True)
    keep.write_bytes(b"x")
    rig.behave(mode="slow", size=2_000_000, delay=0.02)
    task = start(api, first_work(api)["id"])[0]
    wait_for(lambda: task_by_id(api, task["id"])["state"] == "downloading")
    began = time.monotonic()
    api.post(f"{BASE}/{task['id']}/cancel")
    done = ended(api, task["id"])
    assert time.monotonic() - began < 2.0
    assert done["state"] == "cancelled"
    assert final_files(rig) == []
    assert parts_left(rig.settings) == [keep]
    # Nothing keeps writing after it says cancelled.
    assert keep.read_bytes() == b"x"
    assert api.post(f"{BASE}/{task['id']}/cancel").json()["state"] == "cancelled"


def test_cancelling_something_finished_leaves_it_finished(api: TestClient, rig: Rig) -> None:
    rig.behave(size=1000)
    _work, task = run_one(api)
    assert api.post(f"{BASE}/{task['id']}/cancel").json()["state"] == "done"
    assert len(final_files(rig)) == 1


def test_cancelling_a_queued_task_never_starts_it(api: TestClient, rig: Rig) -> None:
    rig.behave(mode="slow", size=2_000_000, delay=0.02)
    tasks = [start(api, work["id"])[0] for work in work_ids(api)[: MAX_RUNNING + 1]]
    queued = tasks[-1]
    assert task_by_id(api, queued["id"])["state"] == "queued"
    assert api.post(f"{BASE}/{queued['id']}/cancel").json()["state"] == "cancelled"
    for task in tasks[:-1]:
        api.post(f"{BASE}/{task['id']}/cancel")
    for task in tasks:
        assert ended(api, task["id"])["state"] == "cancelled"
    assert final_files(rig) == []


def test_cancelled_tasks_can_start_over(api: TestClient, rig: Rig) -> None:
    rig.behave(mode="slow", size=500_000, delay=0.01)
    work = first_work(api)
    task = start(api, work["id"])[0]
    wait_for(lambda: task_by_id(api, task["id"])["state"] == "downloading")
    api.post(f"{BASE}/{task['id']}/cancel")
    ended(api, task["id"])
    rig.behave(size=1000)
    api.post(f"{BASE}/{task['id']}/retry")
    assert ended(api, task["id"])["state"] == "done"


def test_a_late_worker_cannot_change_a_newer_attempt(api: TestClient, rig: Rig) -> None:
    rig.behave(size=1000)
    _work, task = run_one(api)
    queue = queue_of(api)
    with engine_of(api).connect() as connection:
        row = connection.execute(
            select(download_tasks).where(download_tasks.c.id == task["id"])
        ).first()
    assert queue._write(task["id"], row.attempt - 1, state="failed", code="unexpected") is False
    assert task_by_id(api, task["id"])["state"] == "done"


def test_clearing_forgets_failures_and_keeps_finished_files(api: TestClient, rig: Rig) -> None:
    works_ = work_ids(api)
    rig.behave(size=1000)
    done = ended(api, start(api, works_[0]["id"])[0]["id"])
    rig.behave(mode="gone")
    failed = ended(api, start(api, works_[1]["id"])[0]["id"])
    assert failed["state"] == "failed"
    left = api.post(f"{BASE}/clear").json()["tasks"]
    assert [task["id"] for task in left] == [done["id"]]
    assert len(final_files(rig)) == 1


# --- restarts ---


def test_a_restart_reports_instead_of_downloading(settings: Settings, rig: Rig) -> None:
    with client_for(settings) as client:
        prepare(client, rig)
        rig.behave(mode="slow", size=2_000_000, delay=0.02)
        task = start(client, first_work(client)["id"])[0]
        wait_for(lambda: task_by_id(client, task["id"])["state"] == "downloading")
    with client_for(settings) as client:
        client.headers.update(write_headers(client))
        rig.behave(size=2_000_000)
        after = task_by_id(client, task["id"])
        assert after["state"] == "interrupted"
        assert after["message"]
        time.sleep(0.3)
        assert task_by_id(client, task["id"])["state"] == "interrupted"
        assert final_files(rig) == []
        client.post(f"{BASE}/{task['id']}/retry")
        assert ended(client, task["id"])["state"] == "done"
        assert final_files(rig)[0].stat().st_size == 2_000_000


def _crash(client: TestClient, task_id: str, **values: Any) -> None:
    with engine_of(client).begin() as connection:
        connection.execute(
            update(download_tasks).where(download_tasks.c.id == task_id).values(**values)
        )


def test_crash_after_the_move_is_recognized_as_finished(settings: Settings, rig: Rig) -> None:
    with client_for(settings) as client:
        prepare(client, rig)
        rig.behave(size=SIZE)
        _work, task = run_one(client)
        with engine_of(client).connect() as connection:
            row = connection.execute(select(download_tasks)).first()
        _crash(client, task["id"], state="verifying", active_key="x", finished_at=None)
        client.app.state.service.downloads._closing = True  # type: ignore[attr-defined]
    with client_for(settings) as client:
        after = task_by_id(client, task["id"])
        assert after["state"] == "done"
        assert after["fileName"] == row.file_name


def test_crash_before_the_move_is_not_finished(settings: Settings, rig: Rig) -> None:
    with client_for(settings) as client:
        prepare(client, rig)
        rig.behave(size=SIZE)
        _work, task = run_one(client)
        for file in final_files(rig):
            file.unlink()
        _crash(client, task["id"], state="verifying", active_key="x", finished_at=None)
    with client_for(settings) as client:
        assert task_by_id(client, task["id"])["state"] == "interrupted"


def test_a_damaged_final_file_is_not_called_finished_after_a_crash(
    settings: Settings, rig: Rig
) -> None:
    with client_for(settings) as client:
        prepare(client, rig)
        rig.behave(size=SIZE)
        _work, task = run_one(client)
        final_files(rig)[0].write_bytes(b"damaged")
        _crash(client, task["id"], state="verifying", active_key="x", finished_at=None)
    with client_for(settings) as client:
        assert task_by_id(client, task["id"])["state"] == "interrupted"


def test_a_file_removed_later_is_reported_not_assumed(api: TestClient, rig: Rig) -> None:
    rig.behave(size=SIZE)
    work, task = run_one(api)
    final_files(rig)[0].unlink()
    after = task_by_id(api, task["id"])
    assert after["state"] == "done"
    assert after["fileMissing"] is True
    assert api.get(f"/api/v1/works/{work['id']}").json()["installed"] is None
    # Asking again fetches it, rather than pointing at a file that is gone.
    assert ended(api, start(api, work["id"])[0]["id"])["state"] == "done"
    assert len(final_files(rig)) == 1


# --- accounts and visibility ---


def test_logging_out_stops_a_transfer_without_using_a_new_session(
    api: TestClient, rig: Rig
) -> None:
    rig.behave(mode="slow", size=2_000_000, delay=0.02)
    task = start(api, first_work(api)["id"])[0]
    wait_for(lambda: task_by_id(api, task["id"])["state"] == "downloading")
    api.post("/api/v1/sources/dlsite/disconnect")
    done = ended(api, task["id"])
    assert done["state"] == "reauth_required"
    assert done["code"] == "session_changed"
    assert final_files(rig) == []


def test_a_task_of_another_account_is_not_continued(api: TestClient, rig: Rig) -> None:
    rig.behave(mode="slow", size=2_000_000, delay=0.02)
    work = first_work(api)
    task = start(api, work["id"])[0]
    wait_for(lambda: task_by_id(api, task["id"])["state"] == "downloading")
    api.post(f"{BASE}/{task['id']}/pause")
    ended(api, task["id"])
    with engine_of(api).begin() as connection:
        connection.execute(update(source_accounts).values(account_fingerprint="someone-else"))
    rig.behave(size=2_000_000)
    api.post(f"{BASE}/{task['id']}/retry")
    done = ended(api, task["id"])
    assert done["state"] == "failed"
    assert done["code"] == "account_changed"
    assert done["canRetry"] is False
    assert final_files(rig) == []
    assert api.post(f"{BASE}/{task['id']}/retry").status_code == 409


@pytest.mark.parametrize("visibility", ["hidden", "private", "quarantined"])
def test_works_outside_ordinary_views_stay_out_of_downloads(
    api: TestClient, rig: Rig, visibility: str
) -> None:
    rig.behave(size=1000)
    work, task = run_one(api)
    other = work_ids(api)[1]
    for target in (work["id"], other["id"]):
        with engine_of(api).begin() as connection:
            connection.execute(
                update(personal_records)
                .where(personal_records.c.work_id == target)
                .values(visibility=visibility)
            )
    assert api.post(f"/api/v1/works/{other['id']}/download-plan").status_code == 404
    assert api.post(BASE, json={"workId": other["id"]}).status_code == 404
    listed = api.get(BASE).json()
    assert listed["tasks"] == []
    assert listed["activeCount"] == 0
    assert api.post(f"{BASE}/{task['id']}/retry").status_code == 404
    assert api.post(f"{BASE}/{task['id']}/open-folder").status_code == 404


def test_works_the_platform_does_not_offer_are_refused_by_the_server(
    api: TestClient, rig: Rig
) -> None:
    work = first_work(api)
    for column in ({"official_viewer_only": 1}, {"can_download": 0}):
        with engine_of(api).begin() as connection:
            connection.execute(update(works).where(works.c.id == work["id"]).values(**column))
        response = api.post(BASE, json={"workId": work["id"]})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "download_unsupported"
        with engine_of(api).begin() as connection:
            connection.execute(
                update(works)
                .where(works.c.id == work["id"])
                .values(official_viewer_only=None, can_download=None)
            )


def test_unknown_work_and_task_are_not_found(api: TestClient) -> None:
    assert api.post(BASE, json={"workId": "nope"}).status_code == 404
    assert api.post(f"{BASE}/nope/cancel").status_code == 404


def test_requests_without_the_local_token_are_refused(api: TestClient) -> None:
    work = first_work(api)
    response = api.post(
        BASE, json={"workId": work["id"]}, headers={"X-Atlas-CSRF": "wrong", "Origin": "x"}
    )
    assert response.status_code in (400, 403)
    assert api.get(BASE).json()["tasks"] == []


def test_task_requests_cannot_name_a_path(api: TestClient) -> None:
    response = api.post(BASE, json={"workId": first_work(api)["id"], "targetDir": "C:\\Windows"})
    assert response.status_code == 422


def test_open_folder_only_for_a_finished_task(api: TestClient, rig: Rig) -> None:
    rig.behave(mode="slow", size=2_000_000, delay=0.02)
    task = start(api, first_work(api)["id"])[0]
    assert api.post(f"{BASE}/{task['id']}/open-folder").status_code == 409
    api.post(f"{BASE}/{task['id']}/cancel")
    ended(api, task["id"])
    rig.behave(size=1000)
    done = ended(api, start(api, work_ids(api)[1]["id"])[0]["id"])
    assert api.post(f"{BASE}/{done['id']}/open-folder").status_code == 200


# --- nothing leaks, and memory stays small ---


def test_no_address_or_session_in_answers_logs_or_database(
    api: TestClient, rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    rig.behave(parts=2, size=1000)
    work = first_work(api)
    plan = api.post(f"/api/v1/works/{work['id']}/download-plan")
    tasks = start(api, work["id"])
    for task in tasks:
        ended(api, task["id"])
    rig.behave(mode="off_platform")
    api.post(BASE, json={"workId": work_ids(api)[1]["id"]})
    listing = api.get(BASE).text
    for text in (plan.text, listing):
        assert "/home/download" not in text
        assert "/file/" not in text
        assert "synthetic-session" not in text
    with engine_of(api).connect() as connection:
        rows = connection.execute(select(download_tasks)).all()
    stored = " ".join(str(tuple(row)) for row in rows)
    assert "/home/download" not in stored
    assert "synthetic-session" not in stored
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "/home/download" not in logged
    assert "/file/" not in logged
    assert "synthetic-session" not in logged
    assert str(rig.library) not in logged
    assert work["sourceId"] not in logged


_SERVER_PROCESS = """
import sys, time
from app.testing.fake_download_server import FakeDownloadServer
server = FakeDownloadServer(lambda: {"size": int(sys.argv[1])})
print(server.port, flush=True)
time.sleep(120)
"""


def test_a_large_file_does_not_gather_in_memory(api: TestClient, rig: Rig) -> None:
    """The server runs in its own process, so this measures only Atlas's side."""
    size = 40 * 1024 * 1024
    server = subprocess.Popen(
        [sys.executable, "-c", _SERVER_PROCESS, str(size)],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert server.stdout is not None
        port = int(server.stdout.readline())
        queue_of(api)._client_factory = lambda cookies: PlatformDownloadClient(
            cookies,
            entry_url=f"http://127.0.0.1:{port}/api/v3/download",
            allows=lambda url: url.host == "127.0.0.1",
        )
        work = first_work(api)
        tracemalloc.start()
        try:
            task = start(api, work["id"])[0]
            done = ended(api, task["id"], 90)
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
    finally:
        server.kill()
        server.wait()
    assert done["state"] == "done", done
    assert final_files(rig)[0].stat().st_size == size
    # A fraction of the file, whatever its size: reads and hashing use small fixed blocks.
    assert peak < 16 * 1024 * 1024
