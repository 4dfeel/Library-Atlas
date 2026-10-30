"""A work's store images, read when its page is opened. Works outside ordinary views get
nothing and cause no request. The list is kept for a week, and a failed check keeps what was
already known, so a platform problem never empties a page."""

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, Row, update

from app.adapters.dlsite.covers import CoverCache, CoverUnavailable
from app.adapters.dlsite.library import PlatformUnavailable
from app.adapters.dlsite.product import ProductClient
from app.api import models
from app.core.errors import AtlasError
from app.db.engine import writing
from app.db.schema import works
from app.repositories.works import get_ordinary_work

_KEEP_FOR = timedelta(days=7)
_SITE = re.compile(r"dlsite\.com/([a-z0-9_-]{1,32})/")


def _site(row: Row[Any]) -> str:
    match = _SITE.search(row.source_url or "")
    return match.group(1) if match else "home"


def _fresh(checked_at: str | None) -> bool:
    if not checked_at:
        return False
    try:
        return datetime.now(UTC) - datetime.fromisoformat(checked_at) < _KEEP_FOR
    except ValueError:
        return False


def _stored(row: Row[Any]) -> list[dict[str, Any]]:
    try:
        data = json.loads(row.gallery_json or "[]")
    except ValueError:
        return []
    return data if isinstance(data, list) else []


class WorkGallery:
    def __init__(self, engine: Engine, client: ProductClient, images: CoverCache) -> None:
        self._engine = engine
        self._client = client
        self._images = images

    def gallery(self, work_id: str) -> models.GalleryOut:
        with self._engine.connect() as connection:
            row = get_ordinary_work(connection, work_id)
        if row.source_id != "dlsite":
            return models.GalleryOut(images=[])
        known = _stored(row)
        unavailable = False
        intro: str | None = row.description
        if not _fresh(row.gallery_checked_at):
            try:
                product = self._client.get(_site(row), row.source_work_id)
            except PlatformUnavailable:
                unavailable = True
            else:
                known = [
                    {"ref": image.url, "width": image.width, "height": image.height}
                    for image in product.images
                ]
                values: dict[str, Any] = {
                    "gallery_json": json.dumps(known),
                    "gallery_checked_at": datetime.now(UTC).isoformat(),
                }
                # Fills a gap only: the record never overwrites what is already there.
                if intro is None and product.intro:
                    intro = values["description"] = product.intro
                with writing(self._engine).begin() as connection:
                    connection.execute(update(works).where(works.c.id == work_id).values(**values))
        return models.GalleryOut(
            images=[
                models.GalleryImage(
                    url=f"/api/v1/works/{work_id}/gallery/{index}",
                    width=item.get("width"),
                    height=item.get("height"),
                )
                for index, item in enumerate(known)
            ],
            intro=intro,
            unavailable=unavailable,
        )

    def image(self, work_id: str, index: int) -> tuple[Path, str]:
        """By position in the stored list: a request can never name an address to fetch."""
        with self._engine.connect() as connection:
            known = _stored(get_ordinary_work(connection, work_id))
        if not 0 <= index < len(known):
            raise AtlasError("image_unavailable", "没有这张图片。", status=404)
        try:
            return self._images.get(str(known[index].get("ref")))
        except CoverUnavailable:
            raise AtlasError("image_unavailable", "图片暂时无法获取。", status=404) from None
