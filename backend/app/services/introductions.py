"""A work's full store introduction, read when its page is opened and kept for a week. Sync never
walks the store for this. A failed look keeps what was already known, and a page that cannot be
read as an introduction is never stored as one. Works outside ordinary views cause no request."""

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from sqlalchemy import Engine, Row, update

from app.adapters.dlsite.covers import CoverCache, CoverUnavailable
from app.adapters.dlsite.library import PlatformUnavailable, ResponseChanged
from app.adapters.dlsite.store_page import StorePageClient, StorePageGone, parse_introduction
from app.adapters.dlsite.trailers import EMBED_HOST, Trailers
from app.api import models
from app.core.errors import AtlasError
from app.db.engine import writing
from app.db.schema import works
from app.repositories.works import get_ordinary_work

KEEP_FOR = timedelta(days=7)
REFRESH_AFTER = timedelta(seconds=60)
PARSER_VERSION = 2  # A new parser reads every page again, and loses nothing until it succeeds.
_SITE = re.compile(r"dlsite\.com/([a-z0-9_-]{1,32})/")
MESSAGES = {
    "gone": "DLsite 上找不到这部作品的页面，可能已下架。",
    "unavailable": "暂时读取不到 DLsite 的作品页面，可以稍后重试。",
    "changed": "DLsite 的页面和预期不同，没有读取到介绍。",
}


def _stored(row: Row[Any]) -> dict[str, Any] | None:
    try:
        data = json.loads(row.intro_json) if row.intro_json else None
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _has_image(block: dict[str, Any]) -> bool:
    return block.get("type") == "image" or (block.get("type") == "video" and bool(block.get("ref")))


def _age(fetched_at: str | None) -> timedelta | None:
    if not fetched_at:
        return None
    try:
        return datetime.now(UTC) - datetime.fromisoformat(fetched_at)
    except ValueError:
        return None


class WorkIntroductions:
    def __init__(
        self,
        engine: Engine,
        client: StorePageClient,
        images: CoverCache,
        trailers: Trailers | None = None,
    ) -> None:
        self._engine = engine
        self._client = client
        self._images = images
        self._trailers = trailers

    def _read(self, row: Row[Any]) -> tuple[list[dict[str, Any]] | None, str | None]:
        site = _SITE.search(row.source_url or "")
        name = site.group(1) if site else "home"
        url = f"https://www.dlsite.com/{name}/work/=/product_id/{row.source_work_id}.html"
        try:
            blocks = parse_introduction(self._client.fetch(name, row.source_work_id), url)
        except StorePageGone:
            return None, "gone"
        except PlatformUnavailable:
            return None, "unavailable"
        except ResponseChanged:
            return None, "changed"
        players = self._trailers.find(row.source_work_id) if self._trailers else []
        if players:
            # At the top, where the store shows them, in place of a card saying they exist.
            blocks = [
                *players,
                *(
                    block
                    for block in blocks
                    if not (block.get("type") == "video" and block.get("host") == EMBED_HOST)
                ),
            ]
        return blocks, None

    def introduction(self, work_id: str, *, refresh: bool = False) -> models.IntroOut:
        with self._engine.connect() as connection:
            row = get_ordinary_work(connection, work_id)
        if row.source_id != "dlsite":
            return models.IntroOut(status="empty", blocks=[])
        known = _stored(row)
        age = _age(row.intro_fetched_at)
        current = (
            known is not None
            and known.get("version") == PARSER_VERSION
            and age is not None
            and age < (REFRESH_AFTER if refresh else KEEP_FOR)
        )
        problem: str | None = None
        if not current:
            blocks, problem = self._read(row)
            if blocks is not None:
                known = {"version": PARSER_VERSION, "blocks": blocks}
                row_time = datetime.now(UTC).isoformat()
                with writing(self._engine).begin() as connection:
                    connection.execute(
                        update(works)
                        .where(works.c.id == work_id)
                        .values(intro_json=json.dumps(known), intro_fetched_at=row_time)
                    )
                return self._out(work_id, known, row_time, None)
        return self._out(work_id, known, row.intro_fetched_at, problem)

    @staticmethod
    def _out(
        work_id: str, known: dict[str, Any] | None, fetched_at: str | None, problem: str | None
    ) -> models.IntroOut:
        blocks: list[dict[str, Any]] = []
        index = 0
        for block in (known or {}).get("blocks", []):
            if _has_image(block):
                # An Atlas address by position: the page never learns where the image lives.
                shown = {key: value for key, value in block.items() if key != "ref"}
                shown["poster" if block["type"] == "video" else "url"] = (
                    f"/api/v1/works/{work_id}/intro-image/{index}"
                )
                index += 1
                blocks.append(shown)
            else:
                blocks.append(block)
        if known is None:
            status = "unavailable" if problem else "empty"
        else:
            status = "ok" if blocks else "empty"
        return models.IntroOut(
            status=cast(models.IntroStatus, status),
            blocks=blocks,
            fetched_at=fetched_at,
            stale=bool(known is not None and problem),
            problem=problem,
            message=MESSAGES.get(problem) if problem else None,
        )

    def image(self, work_id: str, index: int) -> tuple[Path, str]:
        with self._engine.connect() as connection:
            known = _stored(get_ordinary_work(connection, work_id))
        refs = [
            block["ref"]
            for block in (known or {}).get("blocks", [])
            if _has_image(block) and block.get("ref")
        ]
        if not 0 <= index < len(refs):
            raise AtlasError("image_unavailable", "没有这张图片。", status=404)
        try:
            return self._images.get(str(refs[index]))
        except CoverUnavailable:
            raise AtlasError("image_unavailable", "图片暂时无法获取。", status=404) from None
