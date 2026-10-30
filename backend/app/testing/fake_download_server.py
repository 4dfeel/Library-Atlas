"""A real HTTP server on the loopback address, standing in for the platform's download route.
Bytes travel over a real socket into real files, so transfers, errors and resume are tested
for real; only the platform is pretend. It proves Atlas's handling, never DLsite's behavior.

`behavior` changes what it does, per test:
  mode     normal, login_page, json_error, expired, forbidden, gone, challenge, limited,
           off_platform, to_login, serial, unknown_route, ignore_range, bad_offset, range_416,
           changed_etag, no_length, truncate_once, truncate_always, flaky, wrong_length, empty,
           hostile_name, weak_etag, slow
  size     file size in bytes; parts  number of parts (0 means a single file)
"""

import hashlib
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

CHUNK = 64 * 1024
_PAGE = b"<!DOCTYPE html><html><body>please sign in</body></html>"


def file_bytes(work: str, number: int, size: int) -> bytes:
    """Repeatable made-up content, different for each file."""
    seed = hashlib.sha256(f"{work}:{number}".encode()).digest()
    return (seed * (size // len(seed) + 1))[:size]


@dataclass
class ServerLog:
    """What arrived, so tests can check what was and was not sent."""

    requests: list[dict[str, str | None]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, path: str, headers: Any) -> None:
        with self.lock:
            self.requests.append(
                {
                    "path": path,
                    "range": headers.get("range"),
                    "if_range": headers.get("if-range"),
                    "cookie": headers.get("cookie"),
                }
            )

    def file_requests(self) -> list[dict[str, str | None]]:
        with self.lock:
            return [item for item in self.requests if "/file/" in str(item["path"])]


class FakeDownloadServer:
    def __init__(self, behavior: Any = None) -> None:
        self.behavior: Any = behavior or (lambda: {})
        self.log = ServerLog()
        self.counts: dict[str, int] = {}
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:
                return None

            def do_GET(self) -> None:
                outer._handle(self)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def entry_url(self) -> str:
        return f"{self.origin}/api/v3/download"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def _settings(self) -> dict[str, Any]:
        return dict(self.behavior())

    def _handle(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(handler.path)
        self.log.add(handler.path, handler.headers)
        settings = self._settings()
        try:
            if parsed.path == "/api/v3/download":
                self._entry(handler, parse_qs(parsed.query).get("workno", [""])[0], settings)
            elif parsed.path.startswith("/home/split"):
                self._split_page(handler, parsed.path.rsplit("/", 1)[-1], settings)
            elif "/file/" in parsed.path:
                self._file(handler, parsed.path, settings)
            else:
                self._plain(handler, 404, b"", "text/plain")
        except (ConnectionError, OSError):
            handler.close_connection = True

    @staticmethod
    def _plain(
        handler: BaseHTTPRequestHandler,
        status: int,
        body: bytes,
        kind: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        handler.send_response(status)
        handler.send_header("Content-Type", kind)
        handler.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            handler.send_header(name, value)
        handler.end_headers()
        handler.wfile.write(body)

    def _redirect(self, handler: BaseHTTPRequestHandler, location: str) -> None:
        self._plain(handler, 302, b"", "text/plain", {"Location": location})

    def _entry(self, handler: BaseHTTPRequestHandler, work: str, settings: dict[str, Any]) -> None:
        mode = settings.get("mode", "normal")
        if mode == "expired":
            self._plain(handler, 401, b"{}", "application/json")
        elif mode == "off_platform":
            self._redirect(handler, "http://localhost:9/home/download/=/file/x.zip")
        elif mode == "to_login":
            self._redirect(handler, "https://login.dlsite.com/login")
        elif mode == "serial":
            self._redirect(handler, f"{self.origin}/home/serial/=/product_id/{work}.html")
        elif mode == "unknown_route":
            self._redirect(handler, f"{self.origin}/somewhere/else/{work}")
        elif int(settings.get("parts", 0)):
            self._redirect(handler, f"{self.origin}/home/split/=/product_id/{work}")
        else:
            name = quote(settings.get("name", f"{work}.zip"))
            self._redirect(
                handler, f"{self.origin}/home/download/=/file/{name}/product_id/{work}.html"
            )

    def _split_page(
        self, handler: BaseHTTPRequestHandler, work: str, settings: dict[str, Any]
    ) -> None:
        links = "".join(
            f'<a href="/home/download/=/number/{n}/file/{work}.part{n}.rar/'
            f'product_id/{work}.html">{n}</a>'
            for n in range(1, int(settings.get("parts", 0)) + 1)
        )
        self._plain(handler, 200, f"<html>{links}</html>".encode(), "text/html")

    def _file(self, handler: BaseHTTPRequestHandler, path: str, settings: dict[str, Any]) -> None:
        mode = settings.get("mode", "normal")
        work = path.split("/product_id/")[-1].removesuffix(".html")
        number = int(path.split("/number/")[1].split("/")[0]) if "/number/" in path else 0
        statuses = {"expired": 401, "forbidden": 403, "gone": 404, "limited": 429, "challenge": 403}
        if mode in ("expired", "forbidden", "gone", "limited", "challenge"):
            extra = {"cf-mitigated": "challenge"} if mode == "challenge" else {}
            self._plain(handler, statuses[mode], b"", "text/plain", extra)
            return
        if mode == "login_page":
            self._plain(handler, 200, _PAGE, "text/html; charset=utf-8")
            return
        if mode == "disguised_page":
            self._plain(handler, 200, _PAGE, "application/zip")
            return
        if mode == "json_error":
            self._plain(handler, 200, b'{"error":"denied"}', "application/json")
            return
        seen = self.counts.get(path, 0)
        self.counts[path] = seen + 1
        if mode == "flaky" and seen < int(settings.get("fail_times", 1)):
            self._plain(handler, 503, b"", "text/plain")
            return
        size = int(settings.get("size", 200_000))
        body = b"" if mode == "empty" else file_bytes(work, number, size)
        etag = '"v1"' if mode != "changed_etag" or seen == 0 else '"v2"'
        if mode == "weak_etag":
            etag = 'W/"v1"'
        headers: dict[str, str] = {"ETag": etag}
        if mode == "hostile_name":
            headers["Content-Disposition"] = 'attachment; filename="..\\..\\CON.zip"'
        else:
            headers["Content-Disposition"] = "attachment"
        asked = handler.headers.get("range")
        start = 0
        status = 200
        if asked and mode == "range_416":
            self._plain(handler, 416, b"", "text/plain", {"Content-Range": f"bytes */{size}"})
            return
        if asked and mode != "ignore_range":
            start = int(asked.removeprefix("bytes=").split("-")[0])
            if handler.headers.get("if-range") == etag or mode == "bad_offset":
                status = 206
                reported = start + 7 if mode == "bad_offset" else start
                headers["Content-Range"] = f"bytes {reported}-{size - 1}/{size}"
            else:
                start = 0
        payload = body[start:]
        handler.send_response(status)
        handler.send_header("Content-Type", "application/zip")
        for name, value in headers.items():
            handler.send_header(name, value)
        if mode == "no_length":
            handler.send_header("Connection", "close")
            handler.close_connection = True
        elif mode == "wrong_length":
            handler.send_header("Content-Length", str(len(payload) + 10))
            handler.send_header("Connection", "close")
            handler.close_connection = True
        else:
            handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        cut = None
        if mode == "truncate_always" or (mode == "truncate_once" and seen == 0):
            cut = len(payload) // 2
        if mode == "changed_etag" and seen == 0:
            cut = len(payload) // 2
        delay = float(settings.get("delay", 0.02 if mode == "slow" else 0))
        sent = 0
        for index in range(0, len(payload), CHUNK):
            piece = payload[index : index + CHUNK]
            if cut is not None and sent + len(piece) > cut:
                handler.wfile.write(piece[: cut - sent])
                handler.wfile.flush()
                handler.close_connection = True
                handler.connection.close()
                return
            handler.wfile.write(piece)
            sent += len(piece)
            if delay:
                time.sleep(delay)
