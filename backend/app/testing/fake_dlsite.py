"""Stand-ins for the platform, used only with the test profile. `build_dlsite_auth` refuses
them for a real library. They prove state handling, never that real login works.

The account name selects the behavior. A control file in the test directory lets browser
tests change the platform's answer and break the store while the service is running.
"""

import json
import threading
from collections.abc import Iterator
from pathlib import Path

from app.adapters.dlsite.login_host import LoginEvent, LoginProcess, LoginRequest
from app.adapters.dlsite.session import SessionCheck, SessionCookie
from app.core.credentials import CredentialStoreError

CONTROL_FILE = "fake-platform.json"
_COOKIE = {"name": "synthetic_session", "domain": "play.dlsite.com", "path": "/", "secure": True}


class FakeControl:
    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / CONTROL_FILE

    def read(self) -> dict[str, str]:
        try:
            return dict(json.loads(self._path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return {}


class FakeLoginProcess:
    def __init__(self, request: LoginRequest) -> None:
        self._request = request
        self._cancelled = threading.Event()
        self._proceed = threading.Event()

    def events(self) -> Iterator[LoginEvent]:
        account = self._request.login_id
        if self._request.mode == "window":
            account = "ok"
        if account.startswith("bad"):
            yield LoginEvent("result", "bad_credentials")
        elif account.startswith("changed"):
            yield LoginEvent("result", "form_changed")
        elif account.startswith("crash"):
            yield LoginEvent("result", "browser_unavailable")
        elif account.startswith("slow") or account.startswith("verify"):
            if account.startswith("verify"):
                yield LoginEvent("state", "needs_verification")
            self._cancelled.wait(timeout=30)
            yield LoginEvent("result", "cancelled")
        else:
            yield LoginEvent(
                "result",
                "success",
                [
                    {**_COOKIE, "value": f"synthetic-session-for-{account}"},
                    {"name": "_ga", "value": "x", "domain": ".dlsite.com"},
                    {"name": "other", "value": "x", "domain": "example.com"},
                ],
            )

    def cancel(self) -> None:
        self._cancelled.set()

    def reveal(self) -> None:
        self._proceed.set()


class FakeLoginHost:
    def start(self, request: LoginRequest) -> LoginProcess:
        return FakeLoginProcess(request)


class FakeChecker:
    def __init__(self, control: FakeControl) -> None:
        self._control = control

    def check(self, cookies: list[SessionCookie]) -> SessionCheck:
        return SessionCheck(self._control.read().get("check", "valid"))


class FileTestStore:
    """Test values in the test directory, so restarts work without touching Windows
    credentials. Never used for a real library."""

    def __init__(self, data_dir: Path, control: FakeControl) -> None:
        self._path = data_dir / "fake-credentials.json"
        self._control = control
        self._lock = threading.Lock()

    def _load(self) -> dict[str, str]:
        try:
            return dict(json.loads(self._path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return {}

    def read(self, name: str) -> bytes | None:
        if self._control.read().get("store") == "fail-read":
            raise CredentialStoreError("test store")
        with self._lock:
            value = self._load().get(name)
        return value.encode("latin-1") if value is not None else None

    def write(self, name: str, secret: bytes) -> None:
        if self._control.read().get("store") == "fail-write":
            raise CredentialStoreError("test store")
        with self._lock:
            data = self._load()
            data[name] = secret.decode("latin-1")
            self._path.write_text(json.dumps(data), encoding="utf-8")

    def delete(self, name: str) -> None:
        if self._control.read().get("store") == "fail-delete":
            raise CredentialStoreError("test store")
        with self._lock:
            data = self._load()
            data.pop(name, None)
            self._path.write_text(json.dumps(data), encoding="utf-8")


class FakeFolderPicker:
    """Answers as if the user chose the folder named in the control file."""

    def __init__(self, control: FakeControl) -> None:
        self._control = control

    def pick(self, initial: Path | None) -> Path | None:
        value = self._control.read().get("pick")
        return Path(value) if value else None


class FakeFolderOpener:
    """Opens nothing, so test runs never pop up Explorer windows."""

    def open(self, path: Path) -> None:
        return None
