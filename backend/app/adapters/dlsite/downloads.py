"""Finds and opens the original files of a purchased work.

The entry address answers with a redirect whose target says how the work is delivered: one
file, numbered parts listed on a page, or a page that also shows a serial number. This is
not a public interface: the shape comes from third-party source (dlsite-manager, MIT,
read 2026-10-31) and is confirmed on a real account only when the user downloads a work.

Every hop is checked before anything is sent, and addresses are followed by hand so session
cookies can only reach the platform's own hosts. Addresses may carry permission and never
leave this module: not in errors, logs or return values other than the plan itself.
"""

import html
import logging
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Literal, Protocol

import httpx

from app.adapters.dlsite.library import PlatformUnavailable, ResponseChanged, SessionRejected
from app.adapters.dlsite.session import SessionCookie
from app.domain.download_names import name_from_disposition, name_from_path

logger = logging.getLogger("atlas")

# These log full addresses, which here can carry permission. Whatever started the process.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

ENTRY_URL = "https://play.dlsite.com/api/v3/download"
CHUNK_BYTES = 256 * 1024  # The most a transfer holds in memory at once.
_MAX_REDIRECTS = 8
_MAX_PAGE_BYTES = 512 * 1024
_MAX_PARTS = 500
_TIMEOUT = httpx.Timeout(connect=20.0, read=60.0, write=20.0, pool=20.0)
_PLATFORM = "dlsite.com"
_SPLIT_PAGE = re.compile(r"^/[\w-]+/(download/split|split)(/|$)")
_SERIAL_PAGE = re.compile(r"^/[\w-]+/(download/serial|serial)(/|$)")
_DIRECT = re.compile(r"^/[\w-]+/download(/|$)")
_QUOTED = re.compile(r"""["']([^"'<>]+)["']""")
_PART_NUMBER = re.compile(r"/number/(\d+)(/|$)")
_CONTENT_RANGE = re.compile(r"^bytes (\d+)-(\d+)/(\d+|\*)$")
# Things a file response must not be, however it is labelled.
_PAGE_TYPES = ("text/html", "application/xhtml+xml", "application/json", "text/plain")
_PAGE_STARTS = (b"<!doctype", b"<html", b"<head", b'{"', b"{\n")


class LoginRequired(Exception):
    """A download address sent us to the login page. The session may still work for reading."""


class Challenged(Exception):
    """The platform asks for a check only a person can pass. Never retried or worked around."""


class NoPermission(Exception):
    """The platform refuses this file for this account, or the address has expired."""


class FileGone(Exception):
    """The platform does not know this work or file."""


class RangeRejected(Exception):
    """The server will not serve from this offset."""


class UnexpectedHost(Exception):
    """A redirect pointed outside the platform. Nothing was sent there."""


class NotAFile(Exception):
    """The response is a page or an error body, not the file."""


def platform_url_allowed(url: httpx.URL) -> bool:
    host = url.host.lower()
    return (
        url.scheme == "https"
        and url.port in (None, 443)
        and (host == _PLATFORM or host.endswith(f".{_PLATFORM}"))
    )


def looks_like_page(first_chunk: bytes) -> bool:
    return first_chunk[:256].lstrip(b"\xef\xbb\xbf \t\r\n").lower().startswith(_PAGE_STARTS)


@dataclass(frozen=True, repr=False)
class PlannedFile:
    number: int | None  # The part number; None for a single file.
    url: str


@dataclass(frozen=True, repr=False)
class DownloadPlan:
    kind: Literal["direct", "split", "serial"]
    files: tuple[PlannedFile, ...] = ()


@dataclass(frozen=True, repr=False)
class Validators:
    etag: str | None = None
    last_modified: str | None = None

    @property
    def strong(self) -> str | None:
        """What can safely prove a resource has not changed between two requests."""
        if self.etag and not self.etag.startswith("W/"):
            return self.etag
        return self.last_modified


class OpenedFile:
    """An open response. `offset` is where its bytes belong in the file."""

    def __init__(self, response: httpx.Response, offset: int, total: int | None) -> None:
        self._response = response
        self.offset = offset
        self.total = total
        self.partial = response.status_code == 206
        self.validators = Validators(
            etag=response.headers.get("etag"), last_modified=response.headers.get("last-modified")
        )
        self.name = name_from_disposition(
            response.headers.get("content-disposition")
        ) or name_from_path(response.url.path)

    def chunks(self) -> Iterator[bytes]:
        return self._response.iter_raw(CHUNK_BYTES)

    def close(self) -> None:
        self._response.close()


class DownloadClient(Protocol):
    def plan(self, source_work_id: str) -> DownloadPlan: ...
    def open(self, url: str, offset: int, validators: Validators) -> OpenedFile: ...
    def close(self) -> None: ...


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers.get("retry-after", ""))
    except ValueError:
        return None


def _is_login(url: httpx.URL) -> bool:
    return url.host.lower().startswith("login.") or url.path.rstrip("/").endswith("/login")


class PlatformDownloadClient:
    def __init__(
        self,
        cookies: list[SessionCookie],
        *,
        entry_url: str = ENTRY_URL,
        allows: Callable[[httpx.URL], bool] = platform_url_allowed,
    ) -> None:
        jar = httpx.Cookies()
        for cookie in cookies:
            jar.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)
        self._entry = entry_url
        self._allows = allows
        # Identity: progress and resume offsets must count the bytes that reach the disk.
        self._client = httpx.Client(
            cookies=jar,
            timeout=_TIMEOUT,
            follow_redirects=False,
            headers={"Accept-Encoding": "identity"},
        )

    def close(self) -> None:
        self._client.close()

    def _send(
        self,
        url: httpx.URL,
        headers: dict[str, str] | None = None,
        *,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        if not self._allows(url):
            logger.warning("download address outside the platform: host=%s", url.host)
            raise UnexpectedHost
        request = self._client.build_request("GET", url, headers=headers, params=params)
        try:
            return self._client.send(request, stream=True)
        except httpx.HTTPError:
            raise PlatformUnavailable from None

    def _raise_for_status(self, response: httpx.Response) -> None:
        status = response.status_code
        if status in (200, 206):
            return
        retry_after = _retry_after(response)
        cloudflare = "cf-mitigated" in response.headers
        response.close()
        if status == 401:
            raise SessionRejected
        if status == 403 and cloudflare:
            raise Challenged
        if status in (403, 410):
            raise NoPermission
        if status == 404:
            raise FileGone
        if status == 416:
            raise RangeRejected
        raise PlatformUnavailable(retry_after)

    def _next_hop(self, response: httpx.Response) -> httpx.URL | None:
        if response.status_code not in (301, 302, 303, 307, 308):
            return None
        location = response.headers.get("location")
        response.close()
        if not location:
            raise ResponseChanged
        target = response.url.join(location)
        if _is_login(target):
            raise LoginRequired
        return target

    def plan(self, source_work_id: str) -> DownloadPlan:
        response = self._send(httpx.URL(self._entry), params={"workno": source_work_id})
        target = self._next_hop(response)
        if target is None:
            self._raise_for_status(response)
            response.close()
            raise ResponseChanged  # The entry is only known to answer with a redirect.
        if not self._allows(target):
            logger.warning("download address outside the platform: host=%s", target.host)
            raise UnexpectedHost
        if _SERIAL_PAGE.match(target.path):
            return DownloadPlan("serial")
        if _SPLIT_PAGE.match(target.path):
            return DownloadPlan("split", self._parts(target, source_work_id))
        if _DIRECT.match(target.path):
            return DownloadPlan("direct", (PlannedFile(None, str(target)),))
        # The first two segments name the route, not the work or the user.
        logger.warning("download route not recognized: %s", "/".join(target.path.split("/")[:3]))
        raise ResponseChanged

    def _parts(self, page: httpx.URL, source_work_id: str) -> tuple[PlannedFile, ...]:
        response = self._follow(page)
        self._raise_for_status(response)
        try:
            body = b""
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > _MAX_PAGE_BYTES:
                    raise ResponseChanged
        except httpx.HTTPError:
            raise PlatformUnavailable from None
        finally:
            response.close()
        found: dict[int, str] = {}
        for value in _QUOTED.findall(body.decode("utf-8", "replace")):
            value = html.unescape(value)
            if "/download" not in value or source_work_id not in value:
                continue
            try:
                url = response.url.join(value)
            except httpx.InvalidURL:
                continue
            number = _PART_NUMBER.search(url.path)
            if number and self._allows(url) and _DIRECT.match(url.path):
                found.setdefault(int(number.group(1)), str(url))
        # A gap means Atlas misread the page; a partial set could never be put together.
        if not found or len(found) > _MAX_PARTS or sorted(found) != list(range(1, len(found) + 1)):
            raise ResponseChanged
        return tuple(PlannedFile(number, found[number]) for number in sorted(found))

    def _follow(self, url: httpx.URL, headers: dict[str, str] | None = None) -> httpx.Response:
        for _ in range(_MAX_REDIRECTS):
            response = self._send(url, headers)
            target = self._next_hop(response)
            if target is None:
                return response
            url = target
        raise PlatformUnavailable

    def open(self, url: str, offset: int, validators: Validators) -> OpenedFile:
        headers: dict[str, str] = {}
        if offset > 0 and validators.strong:
            headers = {"Range": f"bytes={offset}-", "If-Range": validators.strong}
        response = self._follow(httpx.URL(url), headers)
        self._raise_for_status(response)
        try:
            return self._describe(response, bool(headers), offset)
        except Exception:
            response.close()
            raise

    @staticmethod
    def _describe(response: httpx.Response, asked_range: bool, offset: int) -> OpenedFile:
        kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if kind in _PAGE_TYPES:
            raise NotAFile
        if response.headers.get("content-encoding", "identity").strip().lower() != "identity":
            raise NotAFile  # Its length would not be the length of the file on disk.
        if response.status_code == 206:
            match = _CONTENT_RANGE.match(response.headers.get("content-range", ""))
            if not asked_range or not match or int(match.group(1)) != offset:
                raise RangeRejected
            total = None if match.group(3) == "*" else int(match.group(3))
            return OpenedFile(response, offset, total)
        length = response.headers.get("content-length", "")
        return OpenedFile(response, 0, int(length) if length.isdigit() else None)
