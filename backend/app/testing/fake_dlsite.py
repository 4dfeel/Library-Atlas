"""Stand-ins for the platform, used only with the test profile. `build_dlsite_auth` refuses
them for a real library. They prove state handling, never that real login works.

The account name selects the behavior. A control file in the test directory lets browser
tests change the platform's answer and break the store while the service is running.
"""

import hashlib
import json
import struct
import threading
import zlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx

from app.adapters.dlsite.library import PlatformUnavailable, ResponseChanged, SessionRejected
from app.adapters.dlsite.login_host import LoginEvent, LoginProcess, LoginRequest
from app.adapters.dlsite.product import Product, ProductImage
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
            # Long enough for the page to show its progress state, as a real login does.
            self._cancelled.wait(timeout=1.5)
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


def _png(width: int, height: int, color: bytes) -> bytes:
    """A flat made-up picture: real image bytes, with nothing to look at."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    row = b"\x00" + color * width
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


def synthetic_image_transport() -> httpx.BaseTransport:
    """Answers image requests in a test library, so no test ever reaches the platform."""

    def answer(request: httpx.Request) -> httpx.Response:
        color = hashlib.sha256(str(request.url).encode()).digest()[:3]
        # Store images come in both shapes: the first of each set stands upright.
        width, height = (360, 640) if "_0." in str(request.url) else (640, 360)
        return httpx.Response(
            200, headers={"content-type": "image/png"}, content=_png(width, height, color)
        )

    return httpx.MockTransport(answer)


class FakeProductClient:
    """A made-up store record. The control file's `gallery` can be `none` or `offline`."""

    def __init__(self, control: FakeControl) -> None:
        self._control = control

    def get(self, site: str, source_work_id: str) -> Product:
        behavior = self._control.read().get("gallery")
        if behavior == "offline":
            raise PlatformUnavailable
        if behavior == "none":
            return Product()
        return Product(
            tuple(
                ProductImage(f"https://img.dlsite.jp/{source_work_id}_{index}.png")
                for index in range(6)
            ),
            "这是合成的作品简介，不对应任何真实作品。",
        )


_FAKE_TYPES = ("RPG", "ADV", "MNG", "ICG", "SOU", "MUS", "MOV", "ET3", "ZZZ")


class FakeLibraryClient:
    """A made-up purchased library. The control file sets its size and how it misbehaves:
    `size`, `sync` (`expired`, `offline`, `changed`, `slow`) and `sync_after` (batches that
    succeed first). Titles are invented."""

    def __init__(self, control: FakeControl) -> None:
        self._control = control
        self._batches = 0

    def _settings(self) -> dict[str, Any]:
        return self._control.read()

    def count(self) -> int:
        return int(self._settings().get("size", 0))

    def owned(self) -> Any:
        return [
            {"workno": f"RJ8{index:05d}", "sales_date": f"2026-0{1 + index % 9}-15T00:00:00+00:00"}
            for index in range(self.count())
        ]

    def works(self, ids: list[str]) -> list[Any]:
        settings = self._settings()
        behavior = settings.get("sync")
        if self._batches >= int(settings.get("sync_after", 0)):
            if behavior == "expired":
                raise SessionRejected
            if behavior == "offline":
                raise PlatformUnavailable(0.01)
            if behavior == "changed":
                raise ResponseChanged
        if behavior == "slow":
            threading.Event().wait(0.5)
        self._batches += 1
        items = []
        for work_id in ids:
            index = int(work_id[3:])
            items.append(
                {
                    "workno": work_id,
                    "name": {"ja_JP": f"合成作品 {index} 号", "en_US": f"Synthetic Work {index}"},
                    "maker": {"id": "RG00001", "name": {"ja_JP": "虚构社团"}},
                    "work_type": _FAKE_TYPES[index % len(_FAKE_TYPES)],
                    "regist_date": f"20{10 + index % 16}-06-01T00:00:00+09:00",
                    "content_size": None if index % 5 == 0 else (index + 1) * 10_000_000,
                    "upgrade_date": settings.get("upgrade"),
                    "tags": [{"class": "genre", "name": "合成样本"}],
                    "work_files": {},
                }
            )
        return items

    def close(self) -> None:
        return None
