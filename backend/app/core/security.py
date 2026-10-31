"""Local request boundary. Binding to loopback alone does not stop a web page in the
user's browser from reaching this service, so every request is checked here:

- Host must be an allowed loopback address (blocks DNS rebinding).
- Browser cross-site requests are refused outright, by Origin and Sec-Fetch-Site.
- Writes also need an allowed Origin and this process's CSRF token. The token is only
  readable by a same-origin page, and changes on every service start.
"""

import hmac
import secrets

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import Settings

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "x-atlas-csrf"


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def _deny(code: str, message: str, status: int = 403) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message, "requestId": None, "retryable": False}},
        status_code=status,
    )


class LocalBoundaryMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings, csrf_token: str) -> None:
        self.app = app
        self.settings = settings
        self.csrf_token = csrf_token

    def _check(self, method: str, path: str, headers: Headers) -> JSONResponse | None:
        if headers.get("host") not in self.settings.allowed_hosts:
            return _deny("host_not_allowed", "请求的地址不被允许。", 421)
        if not path.startswith("/api/"):
            return None
        origin = headers.get("origin")
        if origin is not None and origin not in self.settings.allowed_origins:
            return _deny("origin_not_allowed", "请求来源不被允许。")
        if headers.get("sec-fetch-site") == "cross-site":
            return _deny("origin_not_allowed", "请求来源不被允许。")
        if method in SAFE_METHODS:
            return None
        if origin is None:
            return _deny("origin_required", "请求缺少来源信息。")
        supplied = headers.get(CSRF_HEADER, "")
        if not hmac.compare_digest(supplied, self.csrf_token):
            return _deny("csrf_invalid", "请求令牌已失效，请重试。")
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        denied = self._check(scope["method"], scope["path"], Headers(scope=scope))
        if denied is not None:
            await denied(scope, receive, send)
            return
        await self.app(scope, receive, send)
