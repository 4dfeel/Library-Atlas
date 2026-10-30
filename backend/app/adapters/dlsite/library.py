"""Reads the signed-in user's works from DLsite Play. Only these fixed addresses; responses
never leave this module except as parsed values, and are never logged."""

from typing import Any, Protocol

import httpx

from app.adapters.dlsite.session import SessionCookie

_COUNT_URL = "https://play.dlsite.com/api/v3/content/count"
_SALES_URL = "https://play.dlsite.com/api/v3/content/sales"
_WORKS_URL = "https://play.dlsite.com/api/v3/content/works"
_TIMEOUT = 30.0


class SessionRejected(Exception):
    """The platform says this session is no longer valid."""


class PlatformUnavailable(Exception):
    """Network trouble, rate limit or server error. Says nothing about the session."""

    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("platform unavailable")
        self.retry_after = retry_after


class ResponseChanged(Exception):
    """The response is not what Atlas understands. Holds no response content."""


class LibraryClient(Protocol):
    def count(self) -> int: ...
    def owned(self) -> Any: ...
    def works(self, ids: list[str]) -> list[Any]: ...
    def close(self) -> None: ...


class PlayLibraryClient:
    def __init__(self, cookies: list[SessionCookie]) -> None:
        jar = httpx.Cookies()
        for cookie in cookies:
            jar.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)
        self._client = httpx.Client(cookies=jar, timeout=_TIMEOUT, follow_redirects=False)

    def close(self) -> None:
        self._client.close()

    def _send(self, method: str, url: str, **kwargs: Any) -> Any:
        try:
            response = self._client.request(method, url, **kwargs)
        except httpx.HTTPError:
            raise PlatformUnavailable from None
        status = response.status_code
        if status in (401, 302, 303) or (status == 403 and "cf-mitigated" not in response.headers):
            raise SessionRejected
        if status != 200:
            raise PlatformUnavailable(_retry_after(response))
        try:
            return response.json()
        except ValueError:
            raise ResponseChanged from None

    def count(self) -> int:
        data = self._send("GET", _COUNT_URL, params={"last": 0})
        total = data.get("user") if isinstance(data, dict) else None
        if not isinstance(total, int) or total < 0:
            raise ResponseChanged
        return total

    def owned(self) -> Any:
        return self._send("GET", _SALES_URL, params={"last": 0})

    def works(self, ids: list[str]) -> list[Any]:
        data = self._send("POST", _WORKS_URL, json=ids)
        items = data.get("works") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise ResponseChanged
        return items


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers.get("retry-after", ""))
    except ValueError:
        return None
