"""Session cookies and the minimal check that they still work."""

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

import httpx

_COUNT_URL = "https://play.dlsite.com/api/v3/content/count"
_AUTHORIZE_URL = "https://play.dlsite.com/api/authorize"
_TIMEOUT = 10.0
_PLATFORM_DOMAIN = "dlsite.com"
# Analytics and short-lived bot-score cookies; a session has no use for them.
_DROPPED_PREFIXES = (
    "_ga",
    "_gid",
    "_gcl",
    "_dd_s",
    "_tt",
    "_vwo",
    "_fbp",
    "_uet",
    "__cf_bm",
    "_clck",
)


class SessionCheck(StrEnum):
    VALID = "valid"
    EXPIRED = "expired"  # The platform says this session is no good.
    UNAVAILABLE = "unavailable"  # Could not tell: network, rate limit, platform trouble.


@dataclass(frozen=True, repr=False)
class SessionCookie:
    name: str
    value: str
    domain: str
    path: str = "/"
    secure: bool = True


def session_cookies(raw: list[dict[str, Any]]) -> list[SessionCookie]:
    """Keeps only what a session needs, and only for the platform's own domain."""
    cookies: list[SessionCookie] = []
    for item in raw:
        name, value = str(item.get("name") or ""), str(item.get("value") or "")
        domain = str(item.get("domain") or "").lstrip(".").lower()
        if not name or not value or name.startswith(_DROPPED_PREFIXES):
            continue
        if domain != _PLATFORM_DOMAIN and not domain.endswith(f".{_PLATFORM_DOMAIN}"):
            continue
        cookies.append(
            SessionCookie(
                name, value, domain, str(item.get("path") or "/"), bool(item.get("secure"))
            )
        )
    return cookies


def encode_session(cookies: list[SessionCookie]) -> bytes:
    return json.dumps(
        [[c.name, c.value, c.domain, c.path, c.secure] for c in cookies],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()


def decode_session(raw: bytes) -> list[SessionCookie]:
    """Raises ValueError for anything that is not a stored session."""
    items = json.loads(raw)
    if not isinstance(items, list):
        raise ValueError
    return [SessionCookie(str(a), str(b), str(c), str(d), bool(e)) for a, b, c, d, e in items]


class SessionChecker(Protocol):
    def check(self, cookies: list[SessionCookie]) -> SessionCheck: ...


class PlaySessionChecker:
    """Only ever calls these two fixed addresses. Reads the status, never the body: the
    count endpoint describes the user's library, which this checkpoint does not read."""

    def check(self, cookies: list[SessionCookie]) -> SessionCheck:
        jar = httpx.Cookies()
        for cookie in cookies:
            jar.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)
        try:
            with httpx.Client(cookies=jar, timeout=_TIMEOUT, follow_redirects=False) as client:
                result = self._status(client)
                if result is not SessionCheck.EXPIRED:
                    return result
                # A login may still need its session exchanged for Play; one try only.
                client.get(_AUTHORIZE_URL, headers={"Referer": "https://play.dlsite.com/"})
                return self._status(client)
        except httpx.HTTPError:
            return SessionCheck.UNAVAILABLE

    @staticmethod
    def _status(client: httpx.Client) -> SessionCheck:
        response = client.get(_COUNT_URL, params={"last": 0})
        if response.status_code == 200:
            return SessionCheck.VALID
        if response.status_code in (401, 302, 303) or (
            response.status_code == 403 and "cf-mitigated" not in response.headers
        ):
            return SessionCheck.EXPIRED
        return SessionCheck.UNAVAILABLE
