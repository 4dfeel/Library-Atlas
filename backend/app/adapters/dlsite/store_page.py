"""A work's public store page, turned into plain blocks of text, images and links.

Nothing from the page is passed on as HTML: the parser copies out only what is on the list below,
so scripts, styles, event attributes, forms and frames cannot survive by construction. Addresses
are checked one by one, and no session is ever sent: this page is public. The age cookie only
records the answer a visitor would give on the page's own prompt.
"""

import re
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit

import httpx

from app.adapters.dlsite.library import PlatformUnavailable, ResponseChanged
from app.domain.dlsite_works import cover_address

_URL = "https://www.dlsite.com/{site}/work/=/product_id/{work}.html"
_COOKIES = {"adultchecked": "1", "locale": "zh-cn"}
_TIMEOUT = 20.0
_MAX_PAGE_BYTES = 4 * 1024 * 1024
_MAX_REDIRECTS = 4
_MAX_BLOCKS = 500
_MAX_TEXT = 200_000
_CONTAINER = "work_parts_container"
# Dropped whole, with everything inside them.
_SKIPPED = {
    "script",
    "style",
    "noscript",
    "template",
    "form",
    "button",
    "select",
    "textarea",
    "svg",
    "object",
    "embed",
    "audio",
    "canvas",
    "map",
}
_VOID = {
    "img",
    "br",
    "hr",
    "input",
    "meta",
    "link",
    "area",
    "base",
    "col",
    "source",
    "track",
    "wbr",
}
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BLOCKS = {"p", "div", "section", "article", "blockquote", "center", "dl", "dt", "dd"}
_VIDEO_HOSTS = ("chobit.cc", "chobit.jp", "youtube.com", "youtube-nocookie.com", "youtu.be")


class StorePageGone(Exception):
    """The platform has no page for this work, or no longer has one."""


class StorePageClient(Protocol):
    def fetch(self, site: str, source_work_id: str) -> str: ...


def _safe_link(raw: str | None, base: str) -> str | None:
    """Only the platform's own https pages. Anything else stays as plain text."""
    if not raw:
        return None
    url = urljoin(base, raw.strip())
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not (host == "dlsite.com" or host.endswith(".dlsite.com")):
        return None
    return url


class _Introduction(HTMLParser):
    def __init__(self, base: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base
        self.blocks: list[dict[str, Any]] = []
        self.found = False
        self._depth = 0  # Open elements inside the container; 0 means outside it.
        self._skip = 0
        self._spans: list[dict[str, str]] = []
        self._href: str | None = None
        self._heading: list[str] | None = None
        self._list: list[str] | None = None
        self._item: list[str] | None = None
        self._rows: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._text_size = 0

    # --- collecting ---

    def _flush(self) -> None:
        spans = [span for span in self._spans if span["text"]]
        self._spans = []
        if not spans or not "".join(span["text"] for span in spans).strip():
            return
        spans[0]["text"] = spans[0]["text"].lstrip()
        spans[-1]["text"] = spans[-1]["text"].rstrip()
        self._add({"type": "paragraph", "spans": spans})

    def _add(self, block: dict[str, Any]) -> None:
        if len(self.blocks) < _MAX_BLOCKS:
            self.blocks.append(block)

    def _image(self, attrs: dict[str, str | None]) -> None:
        source = attrs.get("src") or attrs.get("data-src")
        ref = cover_address(urljoin(self.base, source)) if source else None
        if ref is None:
            return
        self._flush()
        block: dict[str, Any] = {"type": "image", "ref": ref}
        alt = (attrs.get("alt") or "").strip()
        if alt:
            block["alt"] = alt[:300]
        for name in ("width", "height"):
            value = attrs.get(name) or ""
            if value.isdigit() and 0 < int(value) < 20_000:
                block[name] = int(value)
        self._add(block)

    def _video(self, attrs: dict[str, str | None]) -> None:
        source = (attrs.get("src") or "").strip()
        if source.startswith("//"):
            source = f"https:{source}"
        parts = urlsplit(source)
        host = (parts.hostname or "").lower()
        if parts.scheme == "https" and any(
            host == name or host.endswith(f".{name}") for name in _VIDEO_HOSTS
        ):
            self._flush()
            self._add({"type": "video", "host": host})

    # --- parsing ---

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if not self._depth:
            if _CONTAINER in (attributes.get("class") or "").split():
                self.found = True
                self._depth = 1
            return
        if tag not in _VOID:
            self._depth += 1
        if self._skip or tag in _SKIPPED:
            if tag not in _VOID:
                self._skip += 1
            return
        if tag == "iframe":
            self._video(attributes)
            self._skip += 1
        elif tag == "img":
            self._image(attributes)
        elif tag == "video":
            self._flush()
            self._add({"type": "video", "host": "dlsite.com"})
            self._skip += 1
        elif tag == "br":
            self._text("\n")
        elif tag == "hr":
            self._flush()
        elif tag == "a":
            self._href = _safe_link(attributes.get("href"), self.base)
        elif tag in _HEADINGS:
            self._flush()
            self._heading = []
        elif tag in ("ul", "ol"):
            self._flush()
            self._list = []
        elif tag == "li":
            self._item = []
        elif tag == "table":
            self._flush()
            self._rows = []
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []
        elif tag in _BLOCKS:
            self._flush()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self._depth or tag in _VOID:
            return
        self._depth -= 1
        if not self._depth:
            self._flush()
            return
        if self._skip:
            self._skip -= 1
            return
        if tag == "a":
            self._href = None
        elif tag in _HEADINGS and self._heading is not None:
            text = " ".join("".join(self._heading).split())
            self._heading = None
            if text:
                self._add({"type": "heading", "text": text})
        elif tag == "li" and self._item is not None:
            text = "".join(self._item).strip()
            if self._list is not None and text:
                self._list.append(text)
            self._item = None
        elif tag in ("ul", "ol") and self._list is not None:
            if self._list:
                self._add({"type": "list", "items": self._list})
            self._list = None
        elif tag in ("td", "th") and self._cell is not None:
            if self._row is not None:
                self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._rows is not None and any(self._row):
                self._rows.append(self._row)
            self._row = None
        elif tag == "table" and self._rows is not None:
            if self._rows:
                self._add({"type": "table", "rows": self._rows})
            self._rows = None
        elif tag in _BLOCKS:
            self._flush()

    def _text(self, data: str) -> None:
        if self._text_size >= _MAX_TEXT:
            return
        self._text_size += len(data)
        if self._heading is not None:
            self._heading.append(data)
        elif self._cell is not None:
            self._cell.append(data)
        elif self._item is not None:
            self._item.append(data)
        elif self._href:
            self._spans.append({"text": data, "href": self._href})
        elif self._spans and "href" not in self._spans[-1]:
            self._spans[-1]["text"] += data
        else:
            self._spans.append({"text": data})

    def handle_data(self, data: str) -> None:
        if not self._depth or self._skip:
            return
        # Source line breaks mean nothing in HTML; <br> arrives separately.
        self._text(re.sub(r"\s+", " ", data))


def parse_introduction(page: str, base: str) -> list[dict[str, Any]]:
    """The introduction's blocks, in page order. A page without the expected section is not an
    empty introduction: it may be a check page or a new layout, so it must never be kept."""
    parser = _Introduction(base)
    parser.feed(page)
    parser.close()
    if not parser.found:
        raise ResponseChanged
    return parser.blocks


class PublicStorePage:
    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport

    def fetch(self, site: str, source_work_id: str) -> str:
        url = _URL.format(site=site, work=source_work_id)
        try:
            with httpx.Client(
                timeout=_TIMEOUT,
                follow_redirects=False,
                cookies=_COOKIES,
                transport=self._transport,
            ) as client:
                # A work can answer from another section of the store. Only a move to this same
                # work on the platform is followed; anywhere else means it has no page.
                for _ in range(_MAX_REDIRECTS):
                    with client.stream(
                        "GET", url, headers={"User-Agent": "Mozilla/5.0"}
                    ) as response:
                        if response.status_code in (301, 302, 303, 307, 308):
                            target = urljoin(url, response.headers.get("location", ""))
                            if _safe_link(target, url) is None or source_work_id not in target:
                                raise StorePageGone
                            url = target
                            continue
                        if response.status_code == 404:
                            raise StorePageGone
                        if response.status_code != 200:
                            raise PlatformUnavailable
                        body = bytearray()
                        for chunk in response.iter_bytes():
                            body += chunk
                            if len(body) > _MAX_PAGE_BYTES:
                                raise ResponseChanged
                        return body.decode("utf-8", "replace")
                raise StorePageGone
        except httpx.HTTPError:
            raise PlatformUnavailable from None
