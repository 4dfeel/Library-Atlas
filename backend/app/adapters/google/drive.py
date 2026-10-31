"""The few Drive calls cloud saves need. Tokens travel in a header, never in an address.

Anything an answer cannot establish is an error, never an empty result: a listing that fails or
stops early must not read as "nothing in the cloud". Uploads follow Google's resumable protocol, so
a dropped connection continues rather than starts again, and a lost answer is found by asking.
"""

import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx

_FILES = "https://www.googleapis.com/drive/v3/files"
_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
_ABOUT = "https://www.googleapis.com/drive/v3/about"
_FIELDS = "id,name,size,md5Checksum,appProperties,createdTime,trashed"
_TIMEOUT = httpx.Timeout(60.0, connect=15.0)
_CHUNK = 8 * 1024 * 1024  # A multiple of 256 KB, as the protocol requires.
_ATTEMPTS = 5
_FOLDER = "application/vnd.google-apps.folder"
_MAX_PAGES = 1000


class DriveAuthProblem(Exception):
    pass


class DriveUnreachable(Exception):
    pass


class DriveQuotaFull(Exception):
    pass


class DriveProblem(Exception):
    pass


class _Rejected(Exception):
    pass


def _reason(response: httpx.Response) -> str:
    try:
        errors = response.json()["error"]["errors"]
        return str(errors[0].get("reason", ""))
    except (ValueError, KeyError, IndexError, TypeError):
        return ""


def _quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


class DriveClient:
    def __init__(
        self,
        token: Callable[[bool], str],
        transport: httpx.BaseTransport | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._token = token
        self._transport = transport
        self._sleep = sleep

    def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        refreshed = False
        for attempt in range(_ATTEMPTS):
            try:
                with httpx.Client(timeout=_TIMEOUT, transport=self._transport) as client:
                    response = client.request(
                        method,
                        url,
                        headers={**headers, "Authorization": f"Bearer {self._token(refreshed)}"},
                        **kwargs,
                    )
            except httpx.HTTPError:
                raise DriveUnreachable from None
            if response.status_code == 401 and not refreshed:
                refreshed = True
                continue
            if response.status_code == 401:
                raise DriveAuthProblem
            reason = _reason(response) if response.status_code == 403 else ""
            if reason == "storageQuotaExceeded":
                raise DriveQuotaFull
            if response.status_code in (429, 500, 502, 503, 504) or reason in (
                "rateLimitExceeded",
                "userRateLimitExceeded",
            ):
                self._sleep(min(2**attempt, 16))
                continue
            return response
        raise DriveUnreachable

    def _ok(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code == 403:
            raise DriveAuthProblem
        if response.status_code not in (200, 201):
            raise DriveProblem
        try:
            data = response.json()
        except ValueError:
            raise DriveProblem from None
        if not isinstance(data, dict):
            raise DriveProblem
        return data

    def about(self) -> dict[str, Any]:
        data = self._ok(
            self._send("GET", _ABOUT, params={"fields": "user(permissionId,displayName)"})
        )
        user = data.get("user")
        if not isinstance(user, dict) or not user.get("permissionId"):
            raise DriveProblem
        return user

    def find(self, properties: dict[str, str]) -> list[dict[str, Any]]:
        """Every file with these properties, all pages of it, or an exception."""
        terms = [
            f"appProperties has {{ key='{_quote(key)}' and value='{_quote(value)}' }}"
            for key, value in properties.items()
        ]
        query = " and ".join([*terms, "trashed = false"])
        return list(self._pages(query))

    def _pages(self, query: str) -> Iterator[dict[str, Any]]:
        token: str | None = None
        for _page in range(_MAX_PAGES):
            params = {
                "q": query,
                "fields": f"nextPageToken,files({_FIELDS})",
                "pageSize": "200",
                "spaces": "drive",
            }
            if token:
                params["pageToken"] = token
            data = self._ok(self._send("GET", _FILES, params=params))
            files = data.get("files")
            if not isinstance(files, list):
                raise DriveProblem
            yield from files
            token = data.get("nextPageToken")
            if not token:
                return
        raise DriveProblem

    def create_folder(self, name: str, properties: dict[str, str]) -> dict[str, Any]:
        return self._ok(
            self._send(
                "POST",
                _FILES,
                params={"fields": _FIELDS},
                json={"name": name, "mimeType": _FOLDER, "appProperties": properties},
            )
        )

    def upload(
        self, name: str, parent: str, properties: dict[str, str], content: bytes | Path, mime: str
    ) -> dict[str, Any]:
        size = len(content) if isinstance(content, bytes) else content.stat().st_size
        started = self._send(
            "POST",
            _UPLOAD,
            params={"uploadType": "resumable", "fields": _FIELDS},
            headers={
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": mime,
                "X-Upload-Content-Length": str(size),
            },
            content=json.dumps(
                {"name": name, "parents": [parent], "appProperties": properties}
            ).encode(),
        )
        session = started.headers.get("location")
        if started.status_code != 200 or not session:
            self._ok(started)
            raise DriveProblem
        return self._send_chunks(session, content, size)

    @staticmethod
    def _read(content: bytes | Path, start: int, length: int) -> bytes:
        if isinstance(content, bytes):
            return content[start : start + length]
        with content.open("rb") as stream:
            stream.seek(start)
            return stream.read(length)

    def _send_chunks(self, session: str, content: bytes | Path, size: int) -> dict[str, Any]:
        position = 0
        stalled = 0
        while True:
            chunk = self._read(content, position, _CHUNK)
            last = position + len(chunk) - 1
            span = f"bytes {position}-{last}/{size}" if chunk else f"bytes */{size}"
            try:
                response = self._send(
                    "PUT", session, content=chunk, headers={"Content-Range": span}
                )
            except DriveUnreachable:
                stalled += 1
                if stalled >= _ATTEMPTS:
                    raise
                self._sleep(min(2**stalled, 16))
                response = self._ask_where(session, size)
            if response.status_code in (200, 201):
                return self._ok(response)
            if response.status_code != 308:
                self._ok(response)
                raise DriveProblem
            received = response.headers.get("range")
            # "bytes=0-42": the next byte to send is 43. No range: nothing has arrived.
            position = int(received.rsplit("-", 1)[1]) + 1 if received else 0

    def _ask_where(self, session: str, size: int) -> httpx.Response:
        return self._send("PUT", session, content=b"", headers={"Content-Range": f"bytes */{size}"})

    def download(self, file_id: str, target: Path, limit: int) -> None:
        """To a file, and no further than `limit`, whatever the listing said it would be."""
        refreshed = False
        for _attempt in range(2):
            try:
                with (
                    httpx.Client(timeout=_TIMEOUT, transport=self._transport) as client,
                    client.stream(
                        "GET",
                        f"{_FILES}/{file_id}",
                        params={"alt": "media"},
                        headers={"Authorization": f"Bearer {self._token(refreshed)}"},
                    ) as response,
                ):
                    if response.status_code == 401 and not refreshed:
                        refreshed = True
                        continue
                    if response.status_code == 401:
                        raise DriveAuthProblem
                    if response.status_code != 200:
                        raise DriveProblem
                    written = 0
                    with target.open("wb") as stream:
                        for block in response.iter_bytes():
                            written += len(block)
                            if written > limit:
                                raise DriveProblem
                            stream.write(block)
                    return
            except httpx.HTTPError:
                raise DriveUnreachable from None
        raise DriveAuthProblem

    def read_json(self, file_id: str, limit: int = 16 * 1024 * 1024) -> Any:
        response = self._send("GET", f"{_FILES}/{file_id}", params={"alt": "media"})
        if response.status_code != 200 or len(response.content) > limit:
            raise DriveProblem
        try:
            return response.json()
        except ValueError:
            raise DriveProblem from None
