"""A work's public store record: its images and short introduction. Anyone can read this
without signing in, so no session is ever attached. Not a documented interface; a record that
is missing or shaped differently simply yields nothing."""

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.adapters.dlsite.library import PlatformUnavailable
from app.domain.dlsite_works import cover_address

_URL = "https://www.dlsite.com/{site}/api/=/product.json"
_TIMEOUT = 15.0
_MAX_IMAGES = 40


@dataclass(frozen=True)
class ProductImage:
    url: str
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class Product:
    images: tuple[ProductImage, ...] = ()
    intro: str | None = None


class ProductClient(Protocol):
    def get(self, site: str, source_work_id: str) -> Product: ...


def _number(value: Any) -> int | None:
    text = str(value)
    return int(text) if text.isdigit() and int(text) > 0 else None


def _image(raw: Any) -> ProductImage | None:
    if not isinstance(raw, dict):
        return None
    url = cover_address(raw.get("url"))
    if url is None:
        return None
    return ProductImage(url, _number(raw.get("width")), _number(raw.get("height")))


def parse_product(data: Any) -> Product:
    """The main image first, then the samples, each address once."""
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return Product()
    record = data[0]
    samples = record.get("image_samples")
    raw_images = [record.get("image_main"), *(samples if isinstance(samples, list) else [])]
    images: dict[str, ProductImage] = {}
    for raw in raw_images:
        image = _image(raw)
        if image is not None:
            images.setdefault(image.url, image)
    intro = record.get("intro_s")
    return Product(
        tuple(images.values())[:_MAX_IMAGES],
        intro.strip() if isinstance(intro, str) and intro.strip() else None,
    )


class PublicProductClient:
    def get(self, site: str, source_work_id: str) -> Product:
        try:
            response = httpx.get(
                _URL.format(site=site),
                params={"workno": source_work_id},
                timeout=_TIMEOUT,
                follow_redirects=False,
            )
            if response.status_code != 200:
                raise PlatformUnavailable
            return parse_product(response.json())
        except (httpx.HTTPError, ValueError):
            raise PlatformUnavailable from None
