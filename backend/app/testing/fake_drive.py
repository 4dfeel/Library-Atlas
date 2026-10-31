"""A made-up Google at the HTTP level, so the real adapter code runs against it, kept in a folder so
two separate libraries can share one "Drive" like two computers do. No test reaches Google.

Control files in the folder: `account` (who is signed in), `faults.json` (a list of one-shot
troubles), `revoked` (the grant is gone). Pages are small on purpose, so paging is really exercised.
"""

import hashlib
import json
import re
import threading
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

_PAGE_SIZE = 2
_lock = threading.RLock()


class FakeDrive:
    def __init__(self, folder: Path) -> None:
        self._folder = folder
        self._blobs = folder / "blobs"
        self._sessions = folder / "sessions"

    # --- state ---

    def _files(self) -> dict[str, dict[str, Any]]:
        path = self._folder / "files.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

    def _save(self, files: dict[str, dict[str, Any]]) -> None:
        self._folder.mkdir(parents=True, exist_ok=True)
        (self._folder / "files.json").write_text(json.dumps(files), encoding="utf-8")

    def account(self) -> str:
        path = self._folder / "account"
        return path.read_text(encoding="utf-8").strip() if path.is_file() else "account-a"

    def _fault(self, name: str) -> str | None:
        path = self._folder / "faults.json"
        if not path.is_file():
            return None
        faults = json.loads(path.read_text(encoding="utf-8"))
        for fault in faults:
            if fault["on"] == name:
                if not fault.get("stay"):
                    faults.remove(fault)
                    path.write_text(json.dumps(faults), encoding="utf-8")
                return str(fault["do"])
        return None

    def files_of_account(self) -> list[dict[str, Any]]:
        with _lock:
            return [item for item in self._files().values() if item["owner"] == self.account()]

    def blob(self, file_id: str) -> bytes:
        return (self._blobs / file_id).read_bytes()

    # --- the service ---

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        with _lock:
            trouble = self._fault("any")
            if trouble == "offline":
                raise httpx.ConnectError("offline", request=request)
            host = request.url.host
            if host == "oauth2.googleapis.com":
                return self._token(request)
            if request.headers.get("authorization", "").endswith("expired"):
                return httpx.Response(401)
            if not request.headers.get("authorization"):
                return httpx.Response(401)
            if self._fault("auth") == "expire":
                return httpx.Response(401)
            path = request.url.path
            if path == "/drive/v3/about":
                account = self.account()
                return httpx.Response(
                    200,
                    json={"user": {"permissionId": account, "displayName": f"合成账号 {account}"}},
                )
            if path == "/upload/drive/v3/files":
                return self._upload(request)
            if path == "/drive/v3/files":
                return self._list(request) if request.method == "GET" else self._create(request)
            match = re.fullmatch(r"/drive/v3/files/([^/]+)", path)
            if match and request.method == "GET":
                return self._media(match.group(1))
        return httpx.Response(404)

    def _token(self, request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        grant = form.get("grant_type", [""])[0]
        if (self._folder / "revoked").is_file():
            return httpx.Response(400, json={"error": "invalid_grant"})
        if grant == "authorization_code":
            if form.get("code", [""])[0] == "refused" or not form.get("code_verifier"):
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(
                200,
                json={"access_token": "access", "expires_in": 3600, "refresh_token": "refresh"},
            )
        if grant == "refresh_token":
            return httpx.Response(200, json={"access_token": "access", "expires_in": 3600})
        return httpx.Response(400, json={"error": "unsupported_grant_type"})

    def _list(self, request: httpx.Request) -> httpx.Response:
        if self._fault("list") == "fail":
            return httpx.Response(400, json={"error": {"errors": [{"reason": "badRequest"}]}})
        query = request.url.params.get("q", "")
        wanted = re.findall(r"key='([^']*)' and value='([^']*)'", query)
        found = [
            item
            for item in self.files_of_account()
            if all(item["appProperties"].get(key) == value for key, value in wanted)
            and not item.get("trashed")
        ]
        found.sort(key=lambda item: item["createdTime"])
        start = int(request.url.params.get("pageToken") or 0)
        answer: dict[str, Any] = {"files": found[start : start + _PAGE_SIZE]}
        if start + _PAGE_SIZE < len(found):
            answer["nextPageToken"] = str(start + _PAGE_SIZE)
        return httpx.Response(200, json=answer)

    def _record(self, metadata: dict[str, Any], content: bytes | None) -> dict[str, Any]:
        files = self._files()
        file_id = uuid.uuid4().hex
        item: dict[str, Any] = {
            "id": file_id,
            "name": metadata.get("name"),
            "appProperties": metadata.get("appProperties", {}),
            "parents": metadata.get("parents", []),
            "owner": self.account(),
            "createdTime": f"{len(files):08d}",
        }
        if content is not None:
            self._blobs.mkdir(parents=True, exist_ok=True)
            (self._blobs / file_id).write_bytes(content)
            item["size"] = str(len(content))
            item["md5Checksum"] = hashlib.md5(content).hexdigest()  # noqa: S324 - what Drive reports.
        files[file_id] = item
        self._save(files)
        return item

    def _create(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=self._record(json.loads(request.content), None))

    def _upload(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            if self._fault("upload_start") == "quota":
                return httpx.Response(
                    403, json={"error": {"errors": [{"reason": "storageQuotaExceeded"}]}}
                )
            session = uuid.uuid4().hex
            self._sessions.mkdir(parents=True, exist_ok=True)
            (self._sessions / f"{session}.json").write_text(
                request.content.decode(), encoding="utf-8"
            )
            (self._sessions / f"{session}.bin").write_bytes(b"")
            location = f"https://www.googleapis.com/upload/drive/v3/files?upload_id={session}"
            return httpx.Response(200, headers={"Location": location})
        session = request.url.params.get("upload_id", "")
        metadata_file = self._sessions / f"{session}.json"
        if not metadata_file.is_file():
            return httpx.Response(404)
        data_file = self._sessions / f"{session}.bin"
        total = int(request.headers["content-range"].rsplit("/", 1)[1])
        done = data_file.read_bytes()
        done += request.content
        data_file.write_bytes(done)
        if len(done) < total:
            headers = {"Range": f"bytes=0-{len(done) - 1}"} if done else {}
            if self._fault("chunk") == "drop":
                raise httpx.ReadTimeout("dropped", request=request)
            return httpx.Response(308, headers=headers)
        kept = done
        if self._fault("upload_end") == "corrupt":
            kept = done[:-1] + bytes([done[-1] ^ 0xFF])
        item = self._record(json.loads(metadata_file.read_text(encoding="utf-8")), kept)
        metadata_file.unlink()
        data_file.unlink()
        if self._fault("upload_end") == "lose_answer":
            raise httpx.ReadTimeout("the answer was lost", request=request)
        return httpx.Response(200, json=item)

    def _media(self, file_id: str) -> httpx.Response:
        path = self._blobs / file_id
        if not path.is_file():
            return httpx.Response(404)
        content = path.read_bytes()
        if self._fault("download") == "corrupt":
            content = content[:-1] + bytes([content[-1] ^ 0xFF])
        return httpx.Response(200, content=content)


class FakeBrowser:
    """Keeps the address it was asked to open, for a test to act as the user's browser."""

    def __init__(self, data_dir: Path) -> None:
        self._file = data_dir / "fake-browser-url"

    def __call__(self, url: str) -> bool:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.write_text(url, encoding="utf-8")
        return True


def redirect_of(url: str) -> tuple[str, str]:
    query = parse_qs(urlsplit(url).query)
    return query["redirect_uri"][0], query["state"][0]
