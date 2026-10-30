"""Service side of the login browser: starts the process and reads its events."""

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

_BACKEND_DIR = Path(__file__).parents[3]
_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW: this helper must not flash a console.


@dataclass(frozen=True, repr=False)
class LoginRequest:
    """`repr=False`: the password must not reach a log through a stray format call."""

    mode: str  # "credentials" or "window"
    storage_path: Path
    login_id: str = ""
    password: str = ""


@dataclass(frozen=True)
class LoginEvent:
    kind: str  # "state" or "result"
    value: str
    cookies: list[dict[str, Any]] = field(default_factory=list, repr=False)


class LoginProcess(Protocol):
    def events(self) -> Iterator[LoginEvent]: ...
    def cancel(self) -> None: ...
    def reveal(self) -> None: ...


class LoginHost(Protocol):
    def start(self, request: LoginRequest) -> LoginProcess: ...


class _BrowserProcess:
    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self._process = process

    def _send(self, line: bytes) -> None:
        stdin = self._process.stdin
        if stdin is None or stdin.closed:
            return
        try:
            stdin.write(line + b"\n")
            stdin.flush()
        except OSError:
            pass

    def events(self) -> Iterator[LoginEvent]:
        stdout = self._process.stdout
        finished = False
        try:
            for raw in stdout or ():
                try:
                    data = json.loads(raw)
                except ValueError:
                    continue
                if data.get("event") == "state":
                    yield LoginEvent("state", str(data.get("state")))
                elif data.get("event") == "result":
                    finished = True
                    yield LoginEvent(
                        "result", str(data.get("outcome")), list(data.get("cookies") or [])
                    )
                    return
        finally:
            self._stop()
        if not finished:
            yield LoginEvent("result", "browser_unavailable")

    def _stop(self) -> None:
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()

    def cancel(self) -> None:
        self._send(b'{"command":"cancel"}')
        if self._process.stdin:
            try:
                self._process.stdin.close()
            except OSError:
                pass

    def reveal(self) -> None:
        self._send(b'{"command":"reveal"}')


class BrowserLoginHost:
    def start(self, request: LoginRequest) -> LoginProcess:
        process = subprocess.Popen(  # noqa: S603 - fixed module, no user input in the arguments.
            [sys.executable, "-m", "app.adapters.dlsite.browser"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=_BACKEND_DIR,
            creationflags=_NO_WINDOW if os.name == "nt" else 0,
        )
        payload = {
            "mode": request.mode,
            "storage_path": str(request.storage_path),
            "login_id": request.login_id,
            "password": request.password,
        }
        browser = _BrowserProcess(process)
        browser._send(json.dumps(payload, ensure_ascii=False).encode())
        return browser
