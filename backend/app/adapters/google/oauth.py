"""Google's installed-app sign-in: the user's own browser, a loopback address, PKCE.

Atlas never sees the Google password. The answer comes back to a port opened for this one attempt,
which closes as soon as it has one, is abandoned, or times out. An answer whose `state` is not this
attempt's is refused, so nothing can replay an old one into a new session.
"""

import base64
import hashlib
import secrets
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - an address.
SCOPE = "https://www.googleapis.com/auth/drive.file"
_TIMEOUT = 20.0
ATTEMPT_SECONDS = 300.0
_PAGE = (
    "<!doctype html><meta charset=utf-8><title>Library Atlas</title>"
    "<body style='font-family:sans-serif;padding:48px'><p>{}</p>"
)


class GoogleAuthFailed(Exception):
    """The grant is gone or was refused: the user has to sign in again."""


class GoogleUnreachable(Exception):
    pass


class Tokens:
    def __init__(self, access: str, expires_in: float, refresh: str | None) -> None:
        self.access = access
        self.expires_in = expires_in
        self.refresh = refresh


def _token_request(fields: dict[str, str], transport: httpx.BaseTransport | None) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=_TIMEOUT, transport=transport) as client:
            response = client.post(TOKEN_URL, data=fields)
    except httpx.HTTPError:
        raise GoogleUnreachable from None
    if response.status_code >= 500:
        raise GoogleUnreachable
    try:
        data = response.json()
    except ValueError:
        raise GoogleUnreachable from None
    if response.status_code != 200 or not isinstance(data, dict) or "access_token" not in data:
        raise GoogleAuthFailed
    return data


def _with_secret(fields: dict[str, str], client_secret: str | None) -> dict[str, str]:
    # A desktop client's secret protects nothing, but some client types still ask for it.
    return {**fields, "client_secret": client_secret} if client_secret else fields


def exchange_code(
    client_id: str,
    client_secret: str | None,
    code: str,
    verifier: str,
    redirect_uri: str,
    transport: httpx.BaseTransport | None = None,
) -> Tokens:
    data = _token_request(
        _with_secret(
            {
                "client_id": client_id,
                "code": code,
                "code_verifier": verifier,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            client_secret,
        ),
        transport,
    )
    return Tokens(
        str(data["access_token"]), float(data.get("expires_in", 0)), data.get("refresh_token")
    )


def refresh_access(
    client_id: str,
    client_secret: str | None,
    refresh: str,
    transport: httpx.BaseTransport | None = None,
) -> Tokens:
    data = _token_request(
        _with_secret(
            {"client_id": client_id, "refresh_token": refresh, "grant_type": "refresh_token"},
            client_secret,
        ),
        transport,
    )
    return Tokens(str(data["access_token"]), float(data.get("expires_in", 0)), None)


class LoopbackAttempt:
    """One sign-in. `on_answer(code, verifier, redirect_uri)` runs at most once."""

    def __init__(
        self,
        client_id: str,
        on_answer: Callable[[str | None, str, str], str],
        *,
        seconds: float = ATTEMPT_SECONDS,
    ) -> None:
        self.state = secrets.token_urlsafe(32)
        self._verifier = secrets.token_urlsafe(64)
        self._on_answer = on_answer
        self._done = threading.Event()
        attempt = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - the base class's name.
                attempt.answer(self)

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                # The request line holds the authorization code.
                return

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._server.timeout = 0.2
        port = self._server.server_address[1]
        self.redirect_uri = f"http://127.0.0.1:{port}"
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(self._verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        self.url = (
            AUTH_URL
            + "?"
            + urlencode(
                {
                    "client_id": client_id,
                    "redirect_uri": self.redirect_uri,
                    "response_type": "code",
                    "scope": SCOPE,
                    "state": self.state,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                    # Without this, a second sign-in comes back with no refresh token.
                    "prompt": "consent",
                    "access_type": "offline",
                }
            )
        )
        self._thread = threading.Thread(
            target=self._serve, args=(seconds,), name="google-signin", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def cancel(self) -> None:
        self._done.set()

    @property
    def finished(self) -> bool:
        return self._done.is_set()

    def _serve(self, seconds: float) -> None:
        waited = 0.0
        try:
            while not self._done.is_set() and waited < seconds:
                self._server.handle_request()
                waited += self._server.timeout or 0.2
        finally:
            self._done.set()
            self._server.server_close()

    def answer(self, request: BaseHTTPRequestHandler) -> None:
        parts = urlsplit(request.path)
        query = parse_qs(parts.query)
        if parts.path != "/" or query.get("state", [""])[0] != self.state or self._done.is_set():
            self._reply(request, 400, "这个登录请求已失效，请回到 Library Atlas 重新连接。")
            return
        self._done.set()
        code = query.get("code", [None])[0]
        message = self._on_answer(code, self._verifier, self.redirect_uri)
        self._reply(request, 200, message)

    @staticmethod
    def _reply(request: BaseHTTPRequestHandler, status: int, message: str) -> None:
        body = _PAGE.format(message).encode("utf-8")
        request.send_response(status)
        request.send_header("Content-Type", "text/html; charset=utf-8")
        request.send_header("Content-Length", str(len(body)))
        request.send_header("Referrer-Policy", "no-referrer")
        request.end_headers()
        request.wfile.write(body)
