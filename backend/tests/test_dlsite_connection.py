"""Connection lifecycle with stand-ins for the platform. These prove state handling and
secret handling; they say nothing about whether a real DLsite login works."""

import json
import logging
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.adapters.dlsite.login_host import LoginEvent, LoginProcess, LoginRequest
from app.adapters.dlsite.login_page import (
    PageKind,
    PageState,
    Sustained,
    classify,
    is_login_page,
)
from app.adapters.dlsite.session import (
    SessionCheck,
    SessionCookie,
    decode_session,
    encode_session,
    session_cookies,
)
from app.core.config import Settings
from app.core.credentials import (
    MAX_BLOB_BYTES,
    CredentialStoreError,
    WindowsCredentialStore,
)
from app.core.session_vault import SessionCorrupt, SessionVault
from app.main import create_app
from app.services.dlsite_auth import DlsiteAuth, mask_account
from app.services.dlsite_factory import build_dlsite_auth
from tests.conftest import ORIGIN, make_settings, write_headers

SENTINEL_PASSWORD = "SENTINEL-PASSWORD-不应出现-9f3a"
SENTINEL_SESSION = "SENTINEL-SESSION-不应出现-71bc"
BASE = "/api/v1/sources/dlsite"


class MemoryStore:
    def __init__(self) -> None:
        self.items: dict[str, bytes] = {}
        self.fail: set[str] = set()

    def read(self, name: str) -> bytes | None:
        if "read" in self.fail:
            raise CredentialStoreError("x")
        return self.items.get(name)

    def write(self, name: str, secret: bytes) -> None:
        if "write" in self.fail or ("write-manifest" in self.fail and name.endswith("manifest")):
            raise CredentialStoreError("x")
        if len(secret) > MAX_BLOB_BYTES:
            raise CredentialStoreError("too large")
        self.items[name] = secret

    def delete(self, name: str) -> None:
        if "delete" in self.fail:
            raise CredentialStoreError("x")
        self.items.pop(name, None)


class ScriptedProcess:
    def __init__(self, events: list[LoginEvent], *, wait: bool) -> None:
        self._events = events
        self._release = threading.Event()
        self._wait = wait
        self.cancelled = False
        self.revealed = False

    def events(self) -> Iterator[LoginEvent]:
        for event in self._events:
            if event.kind == "result" and self._wait:
                self._release.wait(timeout=20)
            yield event

    def finish(self) -> None:
        self._release.set()

    def cancel(self) -> None:
        self.cancelled = True
        self._release.set()

    def reveal(self) -> None:
        self.revealed = True


class ScriptedHost:
    def __init__(self) -> None:
        self.next: list[LoginEvent] = success()
        self.wait = False
        self.requests: list[LoginRequest] = []
        self.processes: list[ScriptedProcess] = []
        self.error: Exception | None = None

    def start(self, request: LoginRequest) -> LoginProcess:
        if self.error:
            raise self.error
        self.requests.append(request)
        process = ScriptedProcess(self.next, wait=self.wait)
        self.processes.append(process)
        return process


class ScriptedChecker:
    def __init__(self) -> None:
        self.result = SessionCheck.VALID
        self.calls = 0
        self.gate: threading.Event | None = None

    def check(self, cookies: list[SessionCookie]) -> SessionCheck:
        self.calls += 1
        if self.gate:
            self.gate.wait(timeout=20)
        return self.result


def success() -> list[LoginEvent]:
    return [
        LoginEvent("state", "submitted"),
        LoginEvent(
            "result",
            "success",
            [
                {"name": "sid", "value": SENTINEL_SESSION, "domain": "play.dlsite.com"},
                {"name": "_ga", "value": "tracking", "domain": ".dlsite.com"},
                {"name": "sid", "value": "elsewhere", "domain": "evil.example"},
            ],
        ),
    ]


class Rig:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = MemoryStore()
        self.host = ScriptedHost()
        self.checker = ScriptedChecker()

    def factory(self, settings: Settings, engine: Engine) -> DlsiteAuth:
        return DlsiteAuth(
            engine, self.store, self.host, self.checker, settings.data_dir / "login-browser"
        )

    def client(self) -> TestClient:
        app = create_app(self.settings, dlsite_factory=self.factory)
        return TestClient(app, base_url=ORIGIN, raise_server_exceptions=False)


@pytest.fixture
def rig(settings: Settings) -> Rig:
    return Rig(settings)


@pytest.fixture
def api(rig: Rig) -> Iterator[TestClient]:
    with rig.client() as client:
        client.headers.update(write_headers(client))
        yield client


def state(client: TestClient) -> dict:
    return client.get(f"{BASE}/connection").json()


def wait_for(client: TestClient, *expected: str) -> dict:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        current = state(client)
        if current["state"] in expected:
            return current
        time.sleep(0.02)
    raise AssertionError(f"still {state(client)}")


def login(client: TestClient, login_id: str = "me@example.test", **extra: object):
    return client.post(
        f"{BASE}/login", json={"loginId": login_id, "password": SENTINEL_PASSWORD, **extra}
    )


# --- first connection ---


def test_starts_not_connected_and_login_connects(api: TestClient, rig: Rig) -> None:
    assert state(api)["state"] == "not_connected"
    assert login(api).status_code == 200
    connected = wait_for(api, "connected")
    assert connected["lastVerifiedAt"]
    assert api.get("/api/v1/sources").json()["sources"][1]["connection"] == "connected"
    # Signing in brings no works with it.
    assert api.get("/api/v1/works").json()["totalVisible"] == 0
    request = rig.host.requests[0]
    assert request.mode == "credentials"
    assert request.password == SENTINEL_PASSWORD


def test_only_session_cookies_of_the_platform_are_kept(api: TestClient, rig: Rig) -> None:
    login(api)
    wait_for(api, "connected")
    stored = b"".join(v for k, v in rig.store.items.items() if not k.endswith("manifest"))
    names = decode_session(stored)
    assert [(c.name, c.domain) for c in names] == [("sid", "play.dlsite.com")]


@pytest.mark.parametrize(
    ("outcome", "code"),
    [
        ("bad_credentials", "bad_credentials"),
        ("form_changed", "form_changed"),
        ("browser_unavailable", "browser_unavailable"),
        ("timeout", "timeout"),
    ],
)
def test_failed_login_saves_nothing_and_says_why(
    api: TestClient, rig: Rig, outcome: str, code: str
) -> None:
    rig.host.next = [LoginEvent("result", outcome)]
    login(api)
    result = wait_for(api, "not_connected")
    deadline = time.monotonic() + 5
    while result.get("code") is None and time.monotonic() < deadline:
        result = state(api)
    assert result["code"] == code
    assert result["message"]
    assert rig.store.items == {}
    assert rig.checker.calls == 0
    assert len(rig.host.requests) == 1  # One attempt per click; never retried on its own.


def test_session_that_fails_its_first_check_is_not_saved(api: TestClient, rig: Rig) -> None:
    rig.checker.result = SessionCheck.EXPIRED
    login(api)
    deadline = time.monotonic() + 5
    while state(api).get("code") != "not_confirmed" and time.monotonic() < deadline:
        time.sleep(0.02)
    assert state(api)["state"] == "not_connected"
    assert state(api)["code"] == "not_confirmed"
    assert rig.store.items == {}


def test_store_failure_never_reports_connected(api: TestClient, rig: Rig) -> None:
    rig.store.fail = {"write"}
    login(api)
    deadline = time.monotonic() + 5
    while state(api).get("code") != "store_failed" and time.monotonic() < deadline:
        time.sleep(0.02)
    current = state(api)
    assert current["code"] == "store_failed"
    assert current["state"] == "not_connected"
    assert rig.store.items == {}


def test_web_login_fallback_takes_no_credentials(api: TestClient, rig: Rig) -> None:
    assert api.post(f"{BASE}/login/window").status_code == 200
    wait_for(api, "connected")
    assert rig.host.requests[0].mode == "window"
    assert rig.host.requests[0].password == ""


def test_verification_is_reported_and_window_can_be_brought_back(api: TestClient, rig: Rig) -> None:
    rig.host.wait = True
    rig.host.next = [LoginEvent("state", "needs_verification"), *success()[1:]]
    login(api)
    current = wait_for(api, "needs_verification")
    assert current["canReveal"] is True
    api.post(f"{BASE}/login/reveal")
    assert rig.host.processes[0].revealed
    rig.host.processes[0].finish()
    wait_for(api, "connected")


# --- attempts and races ---


def test_second_login_while_one_runs_is_refused(api: TestClient, rig: Rig) -> None:
    rig.host.wait = True
    login(api)
    second = login(api)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "login_in_progress"
    assert api.post(f"{BASE}/login/window").status_code == 409
    rig.host.processes[0].finish()
    wait_for(api, "connected")
    assert len(rig.host.requests) == 1


def test_cancel_ends_the_attempt_and_its_late_result_is_ignored(api: TestClient, rig: Rig) -> None:
    rig.host.wait = True
    login(api)
    wait_for(api, "authenticating")
    deadline = time.monotonic() + 5
    while not rig.host.processes and time.monotonic() < deadline:
        time.sleep(0.01)
    assert api.post(f"{BASE}/login/cancel").json()["state"] == "not_connected"
    assert rig.host.processes[0].cancelled
    time.sleep(0.2)  # The scripted process now delivers its success result.
    assert state(api)["state"] == "not_connected"
    assert rig.store.items == {}


def test_cancel_during_the_session_check_discards_the_session(api: TestClient, rig: Rig) -> None:
    rig.checker.gate = threading.Event()
    login(api)
    deadline = time.monotonic() + 5
    while rig.checker.calls == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    api.post(f"{BASE}/login/cancel")
    rig.checker.gate.set()
    time.sleep(0.2)
    assert state(api)["state"] == "not_connected"
    assert rig.store.items == {}


def test_disconnect_during_a_check_is_not_undone_by_its_answer(api: TestClient, rig: Rig) -> None:
    login(api)
    wait_for(api, "connected")
    rig.checker.gate = threading.Event()
    api.post(f"{BASE}/verify")
    wait_for(api, "verifying")
    api.post(f"{BASE}/disconnect")
    rig.checker.gate.set()
    time.sleep(0.2)
    assert state(api)["state"] == "not_connected"
    assert rig.store.items == {}


# --- restart and re-checking ---


def test_session_survives_restart_and_is_checked_once(rig: Rig) -> None:
    with rig.client() as client:
        client.headers.update(write_headers(client))
        login(client)
        wait_for(client, "connected")
    rig.checker.calls = 0
    with rig.client() as client:
        wait_for(client, "connected")
        for _ in range(5):
            client.get("/api/v1/works")
            state(client)
        assert rig.checker.calls == 1  # Pages and polling never touch the platform.
    assert rig.host.requests[0].password == SENTINEL_PASSWORD
    assert len(rig.host.requests) == 1  # No password was needed again.


def restart_with(rig: Rig, check: SessionCheck) -> dict:
    with rig.client() as client:
        client.headers.update(write_headers(client))
        login(client)
        wait_for(client, "connected")
    rig.checker.result = check
    with rig.client() as client:
        return wait_for(client, "connected", "unverified", "reauth_required")


def test_expired_session_asks_for_login_without_retrying(rig: Rig) -> None:
    result = restart_with(rig, SessionCheck.EXPIRED)
    assert result["state"] == "reauth_required"
    assert result["code"] == "session_expired"
    assert len(rig.host.requests) == 1


def test_network_trouble_is_not_reported_as_expired(rig: Rig) -> None:
    result = restart_with(rig, SessionCheck.UNAVAILABLE)
    assert result["state"] == "unverified"
    assert result["code"] == "platform_unavailable"
    assert result["lastVerifiedAt"]
    assert rig.store.items  # The session is kept.


def test_store_read_failure_is_not_blamed_on_the_account(rig: Rig) -> None:
    with rig.client() as client:
        client.headers.update(write_headers(client))
        login(client)
        wait_for(client, "connected")
    rig.store.fail = {"read"}
    with rig.client() as client:
        result = wait_for(client, "unverified", "reauth_required")
    assert result["state"] == "unverified"
    assert result["code"] == "store_unavailable"


def test_damaged_session_asks_for_login(rig: Rig) -> None:
    with rig.client() as client:
        client.headers.update(write_headers(client))
        login(client)
        wait_for(client, "connected")
    part = next(k for k in rig.store.items if not k.endswith("manifest"))
    rig.store.items[part] = b"damaged"
    with rig.client() as client:
        result = wait_for(client, "reauth_required")
    assert result["code"] == "session_missing"


# --- disconnect ---


def test_disconnect_clears_and_stays_cleared_after_restart(rig: Rig, settings: Settings) -> None:
    with rig.client() as client:
        client.headers.update(write_headers(client))
        login(client)
        wait_for(client, "connected")
        browser_dir = settings.data_dir / "login-browser"
        browser_dir.mkdir(exist_ok=True)
        assert client.post(f"{BASE}/disconnect").json()["state"] == "not_connected"
        assert rig.store.items == {}
        assert not browser_dir.exists()
    rig.checker.calls = 0
    with rig.client() as client:
        assert state(client)["state"] == "not_connected"
    assert rig.checker.calls == 0


def test_disconnect_keeps_the_library(rig: Rig, settings: Settings) -> None:
    from tests.conftest import seed_library

    seed_library(settings, 5)
    with rig.client() as client:
        client.headers.update(write_headers(client))
        login(client)
        wait_for(client, "connected")
        client.post(f"{BASE}/disconnect")
        assert client.get("/api/v1/works").json()["totalVisible"] == 5


def test_failed_cleanup_is_reported_and_never_restored(rig: Rig) -> None:
    with rig.client() as client:
        client.headers.update(write_headers(client))
        login(client)
        wait_for(client, "connected")
        rig.store.fail = {"delete"}
        result = client.post(f"{BASE}/disconnect").json()
        assert result["state"] == "disconnect_failed"
        assert result["code"] == "disconnect_failed"
    rig.checker.calls = 0
    with rig.client() as client:
        assert state(client)["state"] == "disconnect_failed"
        assert rig.checker.calls == 0  # The session is never used again.
        rig.store.fail = set()
        client.headers.update(write_headers(client))
        assert client.post(f"{BASE}/disconnect").json()["state"] == "not_connected"
    assert rig.store.items == {}


def test_reconnecting_after_disconnect_works(api: TestClient, rig: Rig) -> None:
    login(api)
    wait_for(api, "connected")
    api.post(f"{BASE}/disconnect")
    login(api)
    wait_for(api, "connected")
    assert len(rig.host.requests) == 2


# --- account identity ---


def test_a_different_account_needs_confirmation(api: TestClient, rig: Rig) -> None:
    login(api, "first@example.test")
    wait_for(api, "connected")
    api.post(f"{BASE}/disconnect")
    refused = login(api, "second@example.test")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "account_mismatch"
    assert len(rig.host.requests) == 1
    assert login(api, "second@example.test", confirmSwitch=True).status_code == 200
    wait_for(api, "connected")


def test_same_account_with_other_spelling_is_the_same(api: TestClient) -> None:
    login(api, "Me@Example.test")
    wait_for(api, "connected")
    api.post(f"{BASE}/disconnect")
    assert login(api, " me@example.test ").status_code == 200


def test_account_name_is_stored_only_as_a_hash(api: TestClient, settings: Settings) -> None:
    login(api, "visible-name@example.test")
    wait_for(api, "connected")
    api.post(f"{BASE}/verify")
    wait_for(api, "connected")
    for path in settings.data_dir.iterdir():
        if path.is_file():
            assert b"visible-name" not in path.read_bytes()


# --- secrets ---


def test_secrets_reach_no_response_log_or_file(
    rig: Rig, settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    responses: list[str] = []
    with caplog.at_level(logging.DEBUG), rig.client() as client:
        client.headers.update(write_headers(client))
        responses.append(login(client).text)
        wait_for(client, "connected")
        responses.append(client.get(f"{BASE}/connection").text)
        responses.append(client.get("/api/v1/sources").text)
        responses.append(client.post(f"{BASE}/verify").text)
        rig.host.next = [LoginEvent("result", "bad_credentials")]
        client.post(f"{BASE}/disconnect")
        responses.append(login(client).text)
        # Invalid requests do not echo what was sent.
        bad = client.post(
            f"{BASE}/login", json={"loginId": "x", "password": SENTINEL_PASSWORD, "bad": 1}
        )
        assert bad.status_code == 422
        responses.append(bad.text)
    combined = "\n".join(responses) + caplog.text
    assert SENTINEL_PASSWORD not in combined
    assert SENTINEL_SESSION not in combined
    assert "me@example.test" not in combined
    for path in settings.data_dir.rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            assert SENTINEL_PASSWORD.encode() not in content
            assert SENTINEL_SESSION.encode() not in content


def test_login_request_repr_hides_the_password() -> None:
    request = LoginRequest("credentials", Path("x"), "me", SENTINEL_PASSWORD)
    assert SENTINEL_PASSWORD not in repr(request)
    assert SENTINEL_SESSION not in repr(SessionCookie("sid", SENTINEL_SESSION, "dlsite.com"))


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"loginId": "", "password": "x"},
        {"loginId": "x", "password": ""},
        {"loginId": "x"},
        {"loginId": "x", "password": "y" * 257},
        {"loginId": "x", "password": "y", "cookies": "z"},
    ],
)
def test_invalid_login_requests_are_refused(api: TestClient, rig: Rig, body: dict) -> None:
    assert api.post(f"{BASE}/login", json=body).status_code == 422
    assert rig.host.requests == []


def test_login_endpoints_need_the_local_boundary(rig: Rig) -> None:
    with rig.client() as client:
        body = {"loginId": "x", "password": SENTINEL_PASSWORD}
        assert client.post(f"{BASE}/login", json=body).status_code == 403
        token = write_headers(client)["X-Atlas-CSRF"]
        assert (
            client.post(
                f"{BASE}/login",
                json=body,
                headers={"Origin": "https://evil.example", "X-Atlas-CSRF": token},
            ).status_code
            == 403
        )
        assert client.post(f"{BASE}/login/window").status_code == 403
        assert client.post(f"{BASE}/disconnect").status_code == 403
        assert rig.host.requests == []


def test_connection_state_is_not_cached_or_widened(api: TestClient) -> None:
    body = api.get(f"{BASE}/connection").json()
    assert set(body) <= {"state", "code", "message", "lastVerifiedAt", "canReveal"}
    assert api.get("/api/v1/ready").status_code == 200  # Readiness ignores the platform.


# --- wiring ---


def test_real_profile_never_uses_stand_ins(tmp_path: Path) -> None:
    from app.adapters.dlsite.login_host import BrowserLoginHost
    from app.adapters.dlsite.session import PlaySessionChecker
    from app.db.bootstrap import open_database

    data = tmp_path / "real"
    data.mkdir()
    real = Settings(profile="real", data_dir=data, port=8765, static_dir=None)
    opened = open_database(real.database_path, real.backup_dir, "real")
    try:
        auth = build_dlsite_auth(real, opened.engine)
    finally:
        opened.engine.dispose()
    assert auth is not None
    assert isinstance(auth._host, BrowserLoginHost)
    assert isinstance(auth._checker, PlaySessionChecker)
    assert isinstance(auth._vault._store, WindowsCredentialStore)
    assert auth._vault._store._namespace == "LibraryAtlas/real/"


def test_test_profile_never_touches_the_real_namespace(tmp_path: Path) -> None:
    from app.db.bootstrap import open_database
    from app.testing.fake_dlsite import FileTestStore

    settings = make_settings(tmp_path / "t")
    opened = open_database(settings.database_path, settings.backup_dir, "test")
    try:
        auth = build_dlsite_auth(settings, opened.engine)
    finally:
        opened.engine.dispose()
    assert auth is not None
    assert isinstance(auth._vault._store, FileTestStore)


# --- session vault ---


@pytest.mark.parametrize("size", [0, 1, MAX_BLOB_BYTES, MAX_BLOB_BYTES + 1, MAX_BLOB_BYTES * 3 + 7])
def test_vault_round_trips_any_size(size: int) -> None:
    store = MemoryStore()
    vault = SessionVault(store, "lib/dlsite/session")
    secret = bytes(index % 251 for index in range(size))
    vault.save(secret)
    assert vault.load() == secret
    vault.delete()
    assert vault.load() is None
    assert store.items == {}


def test_vault_rejects_missing_or_damaged_parts() -> None:
    store = MemoryStore()
    vault = SessionVault(store, "s")
    vault.save(b"x" * (MAX_BLOB_BYTES + 10))
    part = "s/1/1"
    saved = store.items.pop(part)
    with pytest.raises(SessionCorrupt):
        vault.load()
    store.items[part] = b"y" * len(saved)
    with pytest.raises(SessionCorrupt):
        vault.load()
    store.items["s/manifest"] = b"not json"
    with pytest.raises(SessionCorrupt):
        vault.load()


def test_failed_save_keeps_the_previous_session_and_leaves_no_pieces() -> None:
    store = MemoryStore()
    vault = SessionVault(store, "s")
    vault.save(b"old")
    before = dict(store.items)
    store.fail = {"write-manifest"}
    with pytest.raises(CredentialStoreError):
        vault.save(b"new" * 2000)
    assert store.items == before
    store.fail = set()
    assert vault.load() == b"old"


def test_new_save_replaces_the_old_parts() -> None:
    store = MemoryStore()
    vault = SessionVault(store, "s")
    vault.save(b"a" * (MAX_BLOB_BYTES * 2))
    vault.save(b"b")
    assert vault.load() == b"b"
    assert sorted(store.items) == ["s/2/0", "s/manifest"]


def test_vault_works_with_windows_credentials_and_fake_values() -> None:
    try:
        store = WindowsCredentialStore(namespace="LibraryAtlas/pytest/")
    except CredentialStoreError:
        pytest.skip("Windows credential store not available")
    vault = SessionVault(store, "vault")
    secret = b"not-a-real-session" * 400
    assert len(secret) > MAX_BLOB_BYTES
    try:
        vault.save(secret)
        assert vault.load() == secret
    finally:
        vault.delete()
    assert vault.load() is None


# --- cookies and page classification ---


def test_session_filter_and_encoding() -> None:
    cookies = session_cookies(
        [
            {"name": "sid", "value": "a", "domain": ".dlsite.com", "path": "/", "secure": True},
            {"name": "_ga", "value": "b", "domain": ".dlsite.com"},
            {"name": "__cf_bm", "value": "b", "domain": ".login.dlsite.com"},
            {"name": "sid", "value": "c", "domain": "notdlsite.com"},
            {"name": "sid", "value": "d", "domain": "dlsite.com.evil.example"},
            {"name": "", "value": "e", "domain": "dlsite.com"},
        ]
    )
    assert [(c.name, c.domain) for c in cookies] == [("sid", "dlsite.com")]
    assert decode_session(encode_session(cookies))[0].value == "a"
    with pytest.raises(ValueError):
        decode_session(json.dumps({"a": 1}).encode())


LOGIN = "https://login.dlsite.com/login"


@pytest.mark.parametrize(
    ("page", "submitted", "kind"),
    [
        (PageState(), False, PageKind.LOADING),
        (PageState(url=LOGIN, ready="loading"), False, PageKind.LOADING),
        (
            PageState(url="https://evil.example/login", ready="complete"),
            False,
            PageKind.OFF_PLATFORM,
        ),
        (
            PageState(url="http://login.dlsite.com/login", ready="complete", has_form=True),
            False,
            PageKind.OFF_PLATFORM,
        ),
        (PageState(url=LOGIN, ready="complete", has_form=True), False, PageKind.LOGIN_FORM),
        (
            PageState(url=LOGIN, ready="complete", has_form=True, submitted=True),
            True,
            PageKind.LOADING,
        ),
        (PageState(url=LOGIN, ready="complete", has_form=True), True, PageKind.REJECTED),
        (
            PageState(url=LOGIN, ready="complete", has_form=True, captcha=True),
            True,
            PageKind.VERIFICATION,
        ),
        (PageState(url=LOGIN, ready="complete", challenge=True), False, PageKind.VERIFICATION),
        (PageState(url=LOGIN, ready="complete", has_inputs=True), True, PageKind.VERIFICATION),
        (PageState(url=LOGIN, ready="complete"), True, PageKind.LOGGED_IN),
        (PageState(url=LOGIN, ready="complete"), False, PageKind.UNEXPECTED),
        (PageState(url=LOGIN, ready="complete", logged_in_mark=True), True, PageKind.LOGGED_IN),
        (PageState(url="https://www.dlsite.com/home/", ready="complete"), True, PageKind.LOGGED_IN),
    ],
)
def test_page_classification(page: PageState, submitted: bool, kind: PageKind) -> None:
    assert classify(page, was_submitted=submitted) is kind


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (LOGIN, True),
        ("https://login.dlsite.com/login?user=self", True),
        ("https://login.dlsite.com.evil.example/login", False),
        ("http://login.dlsite.com/login", False),
        ("https://login.dlsite.com/other", False),
    ],
)
def test_password_only_goes_to_the_real_login_page(url: str, expected: bool) -> None:
    assert is_login_page(url) is expected


# --- account alias ---


def test_connection_shows_only_a_masked_account(api: TestClient) -> None:
    login(api, "visible-name@example.test")
    connected = wait_for(api, "connected")
    assert connected["accountAlias"] == "vis•••@example.test"
    assert "visible-name" not in json.dumps(connected)


def test_web_login_has_no_account_name(api: TestClient) -> None:
    api.post(f"{BASE}/login/window")
    assert "accountAlias" not in wait_for(api, "connected")


def test_alias_is_gone_after_logout(api: TestClient) -> None:
    login(api)
    wait_for(api, "connected")
    assert "accountAlias" not in api.post(f"{BASE}/disconnect").json()


@pytest.mark.parametrize(
    ("login_id", "alias"),
    [("ab@x.test", "ab•••@x.test"), ("plainname", "pla•••"), (" me@x.test ", "me•••@x.test")],
)
def test_mask_account(login_id: str, alias: str) -> None:
    assert mask_account(login_id) == alias


# --- when the window may appear ---


def test_passing_pages_never_reveal_the_window() -> None:
    gate = Sustained(6.0)
    # The redirect after a submit looks like verification for a moment.
    assert gate.observe(True, now=10.0) is False
    assert gate.observe(True, now=12.0) is False
    assert gate.observe(False, now=13.0) is False
    # It starts over: separate short passes do not add up.
    assert gate.observe(True, now=14.0) is False
    assert gate.observe(True, now=19.9) is False


def test_a_page_that_keeps_asking_reveals_the_window() -> None:
    gate = Sustained(6.0)
    assert gate.observe(True, now=0.0) is False
    assert gate.observe(True, now=6.0) is True
    assert gate.observe(True, now=7.0) is True


def test_signed_in_landing_page_is_not_mistaken_for_verification() -> None:
    # The page DLsite really lands on: no form, no inputs, no 'logged in' wording.
    landing = PageState(url=LOGIN, ready="complete")
    assert classify(landing, was_submitted=True) is PageKind.LOGGED_IN
    assert classify(landing, was_submitted=False, left_form=True) is PageKind.LOGGED_IN
    code_page = PageState(url=LOGIN, ready="complete", has_inputs=True)
    assert classify(code_page, was_submitted=True) is PageKind.VERIFICATION
    assert classify(landing, was_submitted=False) is PageKind.UNEXPECTED


# --- remembered login ---


def login_stored(rig: Rig) -> bool:
    return any("/dlsite/login/" in key for key in rig.store.items)


def test_login_is_not_remembered_unless_asked(api: TestClient, rig: Rig) -> None:
    login(api)
    assert "rememberedAccount" not in wait_for(api, "connected")
    assert not login_stored(rig)


def test_remembered_login_needs_no_typing_and_never_returns_the_password(
    api: TestClient, rig: Rig, settings: Settings
) -> None:
    login(api, "me@example.test", remember=True)
    connected = wait_for(api, "connected")
    assert connected["rememberedAccount"] == "me•••@example.test"
    assert login_stored(rig)
    # Only the credential store holds it, not the database or any other file.
    for path in settings.data_dir.rglob("*"):
        if path.is_file():
            assert SENTINEL_PASSWORD.encode() not in path.read_bytes()
    out = api.post(f"{BASE}/disconnect")
    assert out.json()["rememberedAccount"] == "me•••@example.test"
    assert SENTINEL_PASSWORD not in out.text
    started = api.post(f"{BASE}/login/saved")
    assert started.status_code == 200
    assert SENTINEL_PASSWORD not in started.text
    wait_for(api, "connected")
    assert rig.host.requests[-1].password == SENTINEL_PASSWORD
    assert rig.host.requests[-1].login_id == "me@example.test"


def test_remembered_login_survives_restart_and_can_be_forgotten(rig: Rig) -> None:
    with rig.client() as client:
        client.headers.update(write_headers(client))
        login(client, remember=True)
        wait_for(client, "connected")
    with rig.client() as client:
        client.headers.update(write_headers(client))
        assert state(client)["rememberedAccount"]
        forgotten = client.post(f"{BASE}/saved-login/forget").json()
        assert "rememberedAccount" not in forgotten
        assert not login_stored(rig)
        refused = client.post(f"{BASE}/login/saved")
        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "no_saved_login"


def test_rejected_saved_password_is_deleted_not_retried(api: TestClient, rig: Rig) -> None:
    login(api, remember=True)
    wait_for(api, "connected")
    api.post(f"{BASE}/disconnect")
    rig.host.next = [LoginEvent("result", "bad_credentials")]
    api.post(f"{BASE}/login/saved")
    deadline = time.monotonic() + 5
    while state(api).get("code") != "saved_login_rejected" and time.monotonic() < deadline:
        time.sleep(0.02)
    current = state(api)
    assert current["code"] == "saved_login_rejected"
    assert "rememberedAccount" not in current
    assert not login_stored(rig)
    assert len(rig.host.requests) == 2


def test_failed_login_does_not_remember(api: TestClient, rig: Rig) -> None:
    rig.host.next = [LoginEvent("result", "bad_credentials")]
    login(api, remember=True)
    deadline = time.monotonic() + 5
    while state(api).get("code") != "bad_credentials" and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not login_stored(rig)
    assert "rememberedAccount" not in state(api)


def test_failing_to_remember_does_not_undo_the_login(api: TestClient, rig: Rig) -> None:
    original = rig.store.write

    def refuse_login(name: str, secret: bytes) -> None:
        if "/dlsite/login/" in name:
            raise CredentialStoreError("x")
        original(name, secret)

    rig.store.write = refuse_login  # type: ignore[method-assign]
    login(api, remember=True)
    current = wait_for(api, "connected")
    assert current["code"] == "remember_failed"
    assert "rememberedAccount" not in current
