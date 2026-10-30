"""Sync with a scripted platform and a real database. Proves the sync rules; whether the real
DLsite responses look like this is decided by a real sync, not by these tests."""

import threading
import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.adapters.dlsite.covers import MAX_BYTES, CoverCache, CoverUnavailable
from app.adapters.dlsite.library import PlatformUnavailable, ResponseChanged, SessionRejected
from app.adapters.dlsite.session import SessionCookie, encode_session
from app.core.config import Settings
from app.domain.dlsite_works import cover_address, map_work, owned_works
from app.main import create_app
from app.repositories import accounts
from app.services.dlsite_auth import DlsiteAuth
from app.services.dlsite_sync import BATCH_SIZE, DlsiteSync
from tests.conftest import ORIGIN, write_headers
from tests.test_dlsite_connection import MemoryStore, ScriptedChecker, ScriptedHost

BASE = "/api/v1/sources/dlsite"
SECRET = "SENTINEL-SESSION-SYNC"


def work(index: int, **extra: Any) -> dict[str, Any]:
    return {
        "workno": f"RJ{index:06d}",
        "name": {"ja_JP": f"作品 {index}", "en_US": f"Work {index}"},
        "maker": {"id": "RG1", "name": {"ja_JP": "サークル"}},
        "work_type": "RPG",
        "regist_date": "2025-01-02T00:00:00+09:00",
        "tags": [{"class": "genre", "name": "標準"}],
        "work_files": {"main": f"//img.dlsite.jp/x/{index}.jpg"},
        **extra,
    }


class FakeClient:
    def __init__(self, platform: Platform) -> None:
        self.platform = platform

    def count(self) -> int:
        return self.platform.declared if self.platform.declared is not None else self.size

    @property
    def size(self) -> int:
        return len(self.platform.library)

    def owned(self) -> Any:
        if self.platform.owned_override is not None:
            return self.platform.owned_override
        return [
            {"workno": item["workno"], "sales_date": "2024-03-04T00:00:00+00:00"}
            for item in self.platform.library
        ]

    def works(self, ids: list[str]) -> list[Any]:
        self.platform.batches += 1
        action = self.platform.on_batch.get(self.platform.batches)
        if action is not None:
            if callable(action):
                action()
            else:
                raise action
        if self.platform.items_override is not None:
            return self.platform.items_override
        by_id = {item["workno"]: item for item in self.platform.library}
        return [by_id[work_id] for work_id in ids if work_id in by_id]

    def close(self) -> None:
        self.platform.closed += 1


class Platform:
    def __init__(self) -> None:
        self.library: list[dict[str, Any]] = []
        self.declared: int | None = None
        self.owned_override: Any = None
        self.items_override: list[Any] | None = None
        self.on_batch: dict[int, Any] = {}
        self.batches = 0
        self.closed = 0


class Rig:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.platform = Platform()
        self.store = MemoryStore()
        self.auth: DlsiteAuth | None = None
        self.sync: DlsiteSync | None = None

    def auth_factory(self, settings: Settings, engine: Engine) -> DlsiteAuth:
        self.auth = DlsiteAuth(
            engine, self.store, ScriptedHost(), ScriptedChecker(), settings.data_dir / "b"
        )
        return self.auth

    def sync_factory(self, _settings: Settings, engine: Engine, auth: DlsiteAuth) -> DlsiteSync:
        self.sync = DlsiteSync(
            engine, auth, lambda _cookies: FakeClient(self.platform), sleep=lambda _s: None
        )
        return self.sync

    def client(self) -> TestClient:
        app = create_app(
            self.settings, dlsite_factory=self.auth_factory, dlsite_sync_factory=self.sync_factory
        )
        return TestClient(app, base_url=ORIGIN, raise_server_exceptions=False)

    def connect(self) -> None:
        assert self.auth is not None
        self.auth._vault.save(encode_session([SessionCookie("sid", SECRET, "play.dlsite.com")]))
        with self.auth._engine.begin() as connection:
            accounts.save_connected(
                connection, credential_ref="r", fingerprint="f", alias=None, verified=True
            )


@pytest.fixture
def rig(settings: Settings) -> Rig:
    return Rig(settings)


@pytest.fixture
def api(rig: Rig) -> Iterator[TestClient]:
    with rig.client() as client:
        client.headers.update(write_headers(client))
        rig.connect()
        yield client


def finish(client: TestClient) -> dict:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        job = client.get(f"{BASE}/sync").json().get("job")
        if job and job["state"] not in ("preparing", "reading", "saving"):
            return job
        time.sleep(0.01)
    raise AssertionError("sync did not finish")


def run(client: TestClient) -> dict:
    assert client.post(f"{BASE}/sync").status_code == 200
    return finish(client)


def listed(client: TestClient) -> dict:
    return client.get("/api/v1/works", params={"limit": 100}).json()


# --- first sync ---


def test_nothing_happens_until_the_user_asks(api: TestClient, rig: Rig) -> None:
    rig.platform.library = [work(1)]
    assert api.get(f"{BASE}/sync").json() == {"lastSyncedAt": None, "job": None}
    api.get(f"{BASE}/connection")
    assert rig.platform.batches == 0
    assert listed(api)["totalVisible"] == 0


def test_sync_brings_works_in_visible_and_mapped(api: TestClient, rig: Rig) -> None:
    rig.platform.library = [work(1), work(2, work_type="SOU"), work(3, work_type="MNG")]
    job = run(api)
    assert job["state"] == "succeeded"
    assert (job["total"], job["processed"], job["added"], job["updated"]) == (3, 3, 3, 0)
    page = listed(api)
    assert page["totalVisible"] == 3
    assert page["kindCounts"]["game"] == 1
    assert page["kindCounts"]["audio"] == 1
    assert page["kindCounts"]["image"] == 1
    item = next(i for i in page["items"] if i["sourceId"] == "RJ000001")
    assert item["platform"] == "dlsite"
    assert item["maker"] == "サークル"
    assert item["genre"] == "角色扮演"
    assert item["playtimeMinutes"] is None
    assert item["installed"] is None
    assert item["lastPlayedAt"] is None
    assert item["addedAt"] == "2024-03-04T00:00:00+00:00"
    cover_url = f"/api/v1/works/{item['id']}/cover"
    assert item["cover"] == {"kind": "remote", "index": 0, "url": cover_url}
    assert "img.dlsite.jp" not in str(page)
    assert api.get(f"{BASE}/sync").json()["lastSyncedAt"]
    assert api.get("/api/v1/sources").json()["sources"][1]["lastSyncAt"]


def test_every_spelling_of_the_title_is_searchable(api: TestClient, rig: Rig) -> None:
    rig.platform.library = [work(7)]
    run(api)
    for term in ("作品 7", "work 7", "サークル"):
        assert api.get("/api/v1/works", params={"search": term}).json()["filteredCount"] == 1, term


def test_empty_library_is_a_real_result(api: TestClient) -> None:
    job = run(api)
    assert job["state"] == "succeeded"
    assert job["total"] == 0


def test_large_library_reads_in_batches(api: TestClient, rig: Rig) -> None:
    rig.platform.library = [work(i) for i in range(BATCH_SIZE * 2 + 5)]
    job = run(api)
    assert job["processed"] == BATCH_SIZE * 2 + 5
    assert rig.platform.batches == 3
    assert rig.platform.closed == 1


def test_dashboard_counts_follow(api: TestClient, rig: Rig) -> None:
    rig.platform.library = [work(1), work(2, work_type="MOV")]
    run(api)
    data = api.get("/api/v1/dashboard").json()
    assert data["totals"]["works"] == 2
    assert data["totals"]["games"] == 1
    assert data["totals"]["playedGames"] == 0
    assert data["recent"] == []  # A purchase is not a use.
    assert data["sources"]["dlsite"]["works"] == 2


# --- repeat sync and personal records ---


def test_repeat_sync_adds_nothing_and_keeps_personal_records(api: TestClient, rig: Rig) -> None:
    rig.platform.library = [work(1)]
    run(api)
    item = listed(api)["items"][0]
    url = f"/api/v1/works/{item['id']}/personal"
    api.patch(url, json={"rating": 5, "note": "我的备注", "status": "playing", "favorite": True})
    rig.platform.library = [work(1, name={"ja_JP": "新しい名前"})]
    job = run(api)
    assert (job["added"], job["updated"]) == (0, 1)
    page = listed(api)
    assert page["totalVisible"] == 1
    detail = api.get(f"/api/v1/works/{item['id']}").json()
    assert detail["title"] == "新しい名前"
    assert (detail["rating"], detail["note"], detail["status"], detail["favorite"]) == (
        5,
        "我的备注",
        "playing",
        True,
    )
    assert detail["addedAt"] == item["addedAt"]


def test_missing_fields_do_not_clear_what_is_known(api: TestClient, rig: Rig) -> None:
    rig.platform.library = [work(1)]
    run(api)
    rig.platform.library = [{"workno": "RJ000001", "name": {"ja_JP": "作品 1"}}]
    run(api)
    detail = api.get(f"/api/v1/works/{listed(api)['items'][0]['id']}").json()
    assert detail["maker"] == "サークル"
    assert detail["genre"] == "角色扮演"
    assert detail["cover"]["kind"] == "remote"
    assert detail["tags"] == ["標準"]


def test_a_work_no_longer_listed_stays_with_its_records(api: TestClient, rig: Rig) -> None:
    rig.platform.library = [work(1), work(2)]
    run(api)
    gone = next(i for i in listed(api)["items"] if i["sourceId"] == "RJ000002")
    api.patch(f"/api/v1/works/{gone['id']}/personal", json={"note": "还在"})
    rig.platform.library = [work(1)]
    run(api)
    assert listed(api)["totalVisible"] == 2
    assert api.get(f"/api/v1/works/{gone['id']}").json()["note"] == "还在"


def test_hidden_work_stays_hidden_after_sync(api: TestClient, rig: Rig) -> None:
    from app.repositories.works import set_visibility

    rig.platform.library = [work(1)]
    run(api)
    item = listed(api)["items"][0]
    assert rig.auth is not None
    with rig.auth._engine.begin() as connection:
        set_visibility(connection, item["id"], "private")
    run(api)
    assert listed(api)["totalVisible"] == 0
    assert api.get(f"/api/v1/works/{item['id']}").status_code == 404
    assert api.get(f"/api/v1/works/{item['id']}/cover").status_code == 404


def test_same_id_on_steam_is_a_different_work(api: TestClient, rig: Rig) -> None:
    from app.repositories.works import SourceMetadata, upsert_source_metadata

    assert rig.auth is not None
    with rig.auth._engine.begin() as connection:
        upsert_source_metadata(
            connection,
            SourceMetadata(source_id="steam", source_work_id="RJ000001", kind="game", title="S"),
            visibility="normal",
        )
    rig.platform.library = [work(1)]
    run(api)
    assert listed(api)["totalVisible"] == 2


# --- failures ---


def test_expired_session_stops_and_asks_for_login(api: TestClient, rig: Rig) -> None:
    rig.platform.library = [work(i) for i in range(BATCH_SIZE + 1)]
    rig.platform.on_batch[2] = SessionRejected()
    job = run(api)
    assert job["state"] == "reauth_required"
    assert job["code"] == "session_expired"
    assert api.get(f"{BASE}/connection").json()["state"] == "reauth_required"
    assert listed(api)["totalVisible"] == BATCH_SIZE  # The first batch stays.
    assert api.get(f"{BASE}/sync").json()["lastSyncedAt"] is None


def test_passing_trouble_is_retried_a_limited_number_of_times(api: TestClient, rig: Rig) -> None:
    rig.platform.library = [work(1)]
    rig.platform.on_batch[1] = PlatformUnavailable(0.01)
    assert run(api)["state"] == "succeeded"
    assert rig.platform.batches == 2


def test_lasting_trouble_keeps_the_session_and_reports_partial(api: TestClient, rig: Rig) -> None:
    rig.platform.library = [work(i) for i in range(BATCH_SIZE + 1)]
    for batch in (2, 3, 4):
        rig.platform.on_batch[batch] = PlatformUnavailable(0.01)
    job = run(api)
    assert job["state"] == "partial"
    assert job["code"] == "platform_unavailable"
    assert rig.platform.batches == 4
    assert api.get(f"{BASE}/connection").json()["state"] == "connected"
    assert api.get(f"{BASE}/sync").json()["lastSyncedAt"] is None
    # Running again finishes it without duplicates.
    rig.platform.on_batch.clear()
    assert run(api)["state"] == "succeeded"
    assert listed(api)["totalVisible"] == BATCH_SIZE + 1


def test_failed_sync_with_nothing_saved_is_failed(api: TestClient, rig: Rig) -> None:
    rig.platform.library = [work(1)]
    for batch in (1, 2, 3):
        rig.platform.on_batch[batch] = PlatformUnavailable(0.01)
    assert run(api)["state"] == "failed"
    assert listed(api)["totalVisible"] == 0


@pytest.mark.parametrize(
    "setup",
    [
        lambda p: setattr(p, "owned_override", {"not": "a list"}),
        lambda p: (setattr(p, "declared", 5), setattr(p, "owned_override", [])),
        lambda p: p.on_batch.__setitem__(1, ResponseChanged()),
        lambda p: setattr(p, "items_override", [{"unexpected": True}]),
    ],
)
def test_changed_responses_stop_and_write_nothing(api: TestClient, rig: Rig, setup: Any) -> None:
    rig.platform.library = [work(1)]
    setup(rig.platform)
    job = run(api)
    assert job["state"] == "failed"
    assert job["code"] == "response_changed"
    assert listed(api)["totalVisible"] == 0
    assert api.get(f"{BASE}/sync").json()["lastSyncedAt"] is None


def test_some_unreadable_records_are_skipped_and_reported(api: TestClient, rig: Rig) -> None:
    rig.platform.library = [work(1), work(2)]
    rig.platform.items_override = [work(1), {"workno": "RJ000002"}]
    job = run(api)
    assert job["state"] == "partial"
    assert job["code"] == "some_unreadable"
    assert job["skipped"] == 1
    assert listed(api)["totalVisible"] == 1
    assert api.get(f"{BASE}/sync").json()["lastSyncedAt"] is None


def test_records_for_works_not_asked_for_are_ignored(api: TestClient, rig: Rig) -> None:
    rig.platform.library = [work(1)]
    rig.platform.items_override = [work(1), work(99)]
    run(api)
    assert listed(api)["totalVisible"] == 1


def test_works_the_platform_no_longer_returns_are_counted(api: TestClient, rig: Rig) -> None:
    rig.platform.library = [work(1)]
    rig.platform.owned_override = [{"workno": "RJ000001"}, {"workno": "RJ000002"}]
    job = run(api)
    assert job["state"] == "succeeded"
    assert job["missing"] == 1


def test_duplicate_ids_become_one_work(api: TestClient, rig: Rig) -> None:
    rig.platform.library = [work(1)]
    rig.platform.owned_override = [{"workno": "RJ000001"}, {"workno": "RJ000001"}]
    rig.platform.items_override = [work(1), work(1)]
    job = run(api)
    assert (job["total"], job["added"]) == (1, 1)
    assert listed(api)["totalVisible"] == 1


# --- control ---


def test_needs_a_connected_account(rig: Rig) -> None:
    with rig.client() as client:
        client.headers.update(write_headers(client))
        response = client.post(f"{BASE}/sync")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "not_connected"


def gate_first_batch(rig: Rig) -> threading.Event:
    release = threading.Event()
    rig.platform.on_batch[1] = lambda: release.wait(10)
    return release


def wait_batches(rig: Rig, count: int = 1) -> None:
    deadline = time.monotonic() + 5
    while rig.platform.batches < count and time.monotonic() < deadline:
        time.sleep(0.005)


def test_second_start_joins_the_running_job(api: TestClient, rig: Rig) -> None:
    rig.platform.library = [work(1)]
    release = gate_first_batch(rig)
    first = api.post(f"{BASE}/sync").json()["job"]["id"]
    wait_batches(rig)
    assert api.post(f"{BASE}/sync").json()["job"]["id"] == first
    release.set()
    assert finish(api)["id"] == first
    assert rig.platform.batches == 1


def test_cancel_keeps_what_was_saved_and_says_cancelled(api: TestClient, rig: Rig) -> None:
    rig.platform.library = [work(i) for i in range(BATCH_SIZE + 1)]
    release = threading.Event()
    rig.platform.on_batch[2] = lambda: release.wait(10)
    api.post(f"{BASE}/sync")
    wait_batches(rig, 2)
    api.post(f"{BASE}/sync/cancel")
    release.set()
    job = finish(api)
    assert job["state"] == "cancelled"
    assert listed(api)["totalVisible"] == BATCH_SIZE
    assert api.get(f"{BASE}/sync").json()["lastSyncedAt"] is None


def test_logout_during_sync_stops_late_answers(api: TestClient, rig: Rig) -> None:
    rig.platform.library = [work(1)]
    release = gate_first_batch(rig)
    api.post(f"{BASE}/sync")
    wait_batches(rig)
    api.post(f"{BASE}/disconnect")
    release.set()
    job = finish(api)
    assert job["state"] == "cancelled"
    assert job["code"] == "session_changed"
    assert listed(api)["totalVisible"] == 0


def test_a_job_cut_off_by_restart_is_reported_and_not_rerun(rig: Rig) -> None:
    rig.platform.library = [work(1)]
    with rig.client() as client:
        client.headers.update(write_headers(client))
        rig.connect()
        run(client)
        assert rig.auth is not None
        with rig.auth._engine.begin() as connection:
            connection.exec_driver_sql("UPDATE sync_jobs SET state = 'reading', finished_at = NULL")
    batches = rig.platform.batches
    with rig.client() as client:
        job = client.get(f"{BASE}/sync").json()["job"]
        assert job["state"] == "interrupted"
        assert job["message"]
        assert listed(client)["totalVisible"] == 1
    assert rig.platform.batches == batches


def test_sync_needs_the_local_boundary(rig: Rig) -> None:
    with rig.client() as client:
        assert client.post(f"{BASE}/sync").status_code == 403
        assert client.post(f"{BASE}/sync/cancel").status_code == 403


def test_nothing_private_reaches_the_log(rig: Rig, caplog: pytest.LogCaptureFixture) -> None:
    rig.platform.library = [work(1)]
    with caplog.at_level("INFO", logger="atlas"), rig.client() as client:
        client.headers.update(write_headers(client))
        rig.connect()
        run(client)
    assert "sync fields: " in caplog.text
    assert "sync type codes: RPG=1" in caplog.text
    for private in ("作品 1", "Work 1", "サークル", "RJ000001", SECRET, "img.dlsite.jp"):
        assert private not in caplog.text


# --- mapping ---


def test_mapping_keeps_unknowns_unknown() -> None:
    mapped = map_work({"workno": "RJ1", "name": "题名", "work_type": "NEW"})
    assert mapped is not None
    assert mapped.kind == "other"
    assert mapped.raw_kind == "NEW"
    assert mapped.genre is None
    assert mapped.maker is None
    assert mapped.cover_ref is None
    assert mapped.tags == ()
    assert mapped.local_state == "unknown"
    assert mapped.playtime_minutes is None


def test_kind_comes_from_the_type_code_only() -> None:
    for code, kind in (
        ("RPG", "game"),
        ("DNV", "game"),
        ("MNG", "image"),
        ("VCM", "image"),
        ("SOU", "audio"),
        ("MOV", "video"),
        ("NRE", "other"),
    ):
        mapped = map_work({"workno": "RJ1", "name": "音声 RPG 漫画", "work_type": code})
        assert mapped is not None
        assert mapped.kind == kind, code
    untyped = map_work({"workno": "RJ1", "name": "ゲーム"})
    assert untyped is not None
    assert untyped.kind == "other"


@pytest.mark.parametrize(
    "raw",
    [None, "x", {}, {"workno": ""}, {"workno": "RJ1"}, {"workno": 5, "name": "x"}, {"name": "x"}],
)
def test_records_without_identity_or_title_are_rejected(raw: Any) -> None:
    assert map_work(raw) is None


def test_title_prefers_chinese_and_keeps_other_spellings() -> None:
    names = {"ja_JP": "日本語", "zh_CN": "中文", "en_US": "EN"}
    mapped = map_work({"workno": "RJ1", "name": names})
    assert mapped is not None
    assert mapped.title == "中文"
    assert set(mapped.alt_titles) == {"日本語", "EN"}


def test_identity_is_opaque() -> None:
    mapped = map_work({"workno": "BJ00123", "name": "x"})
    assert mapped is not None
    assert mapped.source_work_id == "BJ00123"


def test_owned_list_handles_duplicates_and_junk() -> None:
    assert owned_works({"a": 1}) is None
    result = owned_works(
        [{"workno": "A", "sales_date": "d"}, {"workno": "A"}, {"x": 1}, "junk", {"workno": ""}]
    )
    assert result is not None
    assert [(w.source_work_id, w.acquired_at) for w in result] == [("A", "d")]


# --- covers ---


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("//img.dlsite.jp/a.jpg", "https://img.dlsite.jp/a.jpg"),
        ("https://img.dlsite.jp/a.jpg", "https://img.dlsite.jp/a.jpg"),
        ("http://img.dlsite.jp/a.jpg", None),
        ("https://evil.example/a.jpg", None),
        ("https://img.dlsite.jp.evil.example/a.jpg", None),
        ("file:///c:/x.jpg", None),
        ("", None),
        (None, None),
    ],
)
def test_only_platform_image_addresses_are_kept(value: Any, expected: str | None) -> None:
    assert cover_address(value) == expected


def cache_with(tmp_path: Any, handler: Any) -> CoverCache:
    return CoverCache(tmp_path / "covers", lambda: httpx.MockTransport(handler))


URL = "https://img.dlsite.jp/a.jpg"


def test_cover_is_fetched_once_without_a_session(tmp_path: Any) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=b"jpeg-bytes")

    cache = cache_with(tmp_path, handler)
    path, content_type = cache.get(URL)
    assert path.read_bytes() == b"jpeg-bytes"
    assert content_type == "image/jpeg"
    assert path.parent == tmp_path / "covers"
    assert "img" not in path.name
    cache.get(URL)
    assert len(calls) == 1
    assert "cookie" not in calls[0].headers


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(404, headers={"content-type": "image/jpeg"}),
        httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>"),
        httpx.Response(302, headers={"location": "https://evil.example/x"}),
        httpx.Response(200, headers={"content-type": "image/jpeg"}, content=b"x" * (MAX_BYTES + 1)),
    ],
)
def test_bad_cover_responses_leave_nothing_behind(tmp_path: Any, response: httpx.Response) -> None:
    cache = cache_with(tmp_path, lambda _request: response)
    with pytest.raises(CoverUnavailable):
        cache.get(URL)
    assert not list((tmp_path / "covers").glob("*")) if (tmp_path / "covers").exists() else True


def test_addresses_off_the_platform_are_never_requested(tmp_path: Any) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not be requested")

    cache = cache_with(tmp_path, handler)
    for url in ("https://evil.example/a.jpg", "http://img.dlsite.jp/a.jpg", "//img.dlsite.jp/a"):
        with pytest.raises(CoverUnavailable):
            cache.get(url)


def test_network_failure_is_only_a_missing_cover(tmp_path: Any) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(CoverUnavailable):
        cache_with(tmp_path, handler).get(URL)
