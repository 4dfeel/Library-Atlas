"""Fetches and caches cover images. This is not a general fetcher: the address comes from the
database, must be on the platform's image hosts, redirects are not followed, the response
must be an image of limited size, and no session is ever sent."""

import hashlib
import os
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

import httpx

from app.domain.dlsite_works import cover_address

MAX_BYTES = 8 * 1024 * 1024
_TIMEOUT = 15.0
_MAX_CONCURRENT = 4
_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


class CoverUnavailable(Exception):
    pass


class CoverCache:
    def __init__(
        self, directory: Path, transport: Callable[[], httpx.BaseTransport | None] = lambda: None
    ) -> None:
        self._directory = directory
        self._transport = transport
        self._slots = threading.BoundedSemaphore(_MAX_CONCURRENT)

    def _base(self, url: str) -> Path:
        # Named by the address's hash: no title or remote text ever reaches a file path.
        return self._directory / hashlib.sha256(url.encode()).hexdigest()

    def get(self, url: str) -> tuple[Path, str]:
        """The cached file and its type, fetching it if needed. A failed fetch leaves any
        older copy alone, and a missing cover never affects the work itself."""
        if cover_address(url) != url:
            raise CoverUnavailable
        base = self._base(url)
        for content_type, suffix in _TYPES.items():
            cached = base.with_suffix(suffix)
            if cached.is_file():
                return cached, content_type
        with self._slots:
            return self._fetch(url, base)

    def _fetch(self, url: str, base: Path) -> tuple[Path, str]:
        try:
            with (
                httpx.Client(
                    timeout=_TIMEOUT, follow_redirects=False, transport=self._transport()
                ) as client,
                client.stream("GET", url) as response,
            ):
                content_type = response.headers.get("content-type", "").split(";")[0].strip()
                suffix = _TYPES.get(content_type)
                if response.status_code != 200 or suffix is None:
                    raise CoverUnavailable
                self._directory.mkdir(parents=True, exist_ok=True)
                target = base.with_suffix(suffix)
                handle, temporary = tempfile.mkstemp(dir=self._directory)
                try:
                    size = 0
                    with os.fdopen(handle, "wb") as file:
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > MAX_BYTES:
                                raise CoverUnavailable
                            file.write(chunk)
                    os.replace(temporary, target)
                except BaseException:
                    Path(temporary).unlink(missing_ok=True)
                    raise
                return target, content_type
        except (httpx.HTTPError, OSError):
            raise CoverUnavailable from None
