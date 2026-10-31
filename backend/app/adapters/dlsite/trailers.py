"""A work's preview players. The store page has none in its HTML: its script asks chobit, the
platform's preview host, which answers publicly by work number. No session is ever sent, and only
addresses on that host are kept: they end up in a frame on the user's page.
"""

from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from app.domain.dlsite_works import cover_address

_URL = "https://chobit.cc/api/v1/dlsite/embed"
_TIMEOUT = 15.0
_MAX_BYTES = 256 * 1024
_MAX_TRAILERS = 5
_MEDIA = {"video", "audio"}
EMBED_HOST = "chobit.cc"


class Trailers(Protocol):
    def find(self, source_work_id: str) -> list[dict[str, Any]]: ...


def _embed(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parts = urlsplit(value)
    if parts.scheme != "https" or parts.hostname != EMBED_HOST:
        return None
    return value if parts.path.startswith("/embed/") else None


def _size(value: Any) -> int | None:
    return value if isinstance(value, int) and 0 < value <= 8192 else None


def parse_trailers(data: Any) -> list[dict[str, Any]]:
    """Blocks for the introduction. Anything not plainly a player on that host is left out."""
    items = data.get("works") if isinstance(data, dict) else None
    blocks: list[dict[str, Any]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or item.get("file_type") not in _MEDIA:
            continue
        embed = _embed(item.get("embed_url"))
        if embed is None:
            continue
        blocks.append(
            {
                "type": "video",
                "host": EMBED_HOST,
                "media": item["file_type"],
                "embed": embed,
                "ref": cover_address(item.get("thumb")),
                "width": _size(item.get("embed_width")),
                "height": _size(item.get("embed_height")),
            }
        )
    return blocks[:_MAX_TRAILERS]


class PublicTrailers:
    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport

    def find(self, source_work_id: str) -> list[dict[str, Any]]:
        """Nothing is the answer to any trouble: the introduction does not depend on this."""
        try:
            with httpx.Client(
                timeout=_TIMEOUT, follow_redirects=False, transport=self._transport
            ) as client:
                response = client.get(
                    _URL,
                    params={"workno": source_work_id},
                    headers={"User-Agent": "Mozilla/5.0"},
                )
            if response.status_code != 200 or len(response.content) > _MAX_BYTES:
                return []
            return parse_trailers(response.json())
        except (httpx.HTTPError, ValueError):
            return []
