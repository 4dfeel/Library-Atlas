"""DLsite library records → Atlas metadata. Pure, so every mapping rule is tested directly.

Field names first came from third-party code (dlsite-async); a real sync on 2026-10-31
confirmed the ones used here. They are still not a published contract.
Anything unexpected becomes "unknown" rather than a guess; a record without its identity
or a title is rejected so that a changed response cannot fill the database with blanks.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from app.repositories.works import SourceMetadata

# DLsite work_type → (Atlas kind, display genre). Not on this list means "other", with the
# original code kept in raw_kind so a later mapping can correct it.
WORK_TYPES: Mapping[str, tuple[str, str]] = {
    "RPG": ("game", "角色扮演"),
    "ACN": ("game", "动作"),
    "ADV": ("game", "冒险"),
    "SLN": ("game", "模拟"),
    "STG": ("game", "射击"),
    "PZL": ("game", "解谜"),
    "QIZ": ("game", "问答"),
    "TBL": ("game", "桌面"),
    "TYP": ("game", "打字"),
    "DNV": ("game", "数字小说"),
    "ETC": ("game", "其他游戏"),
    "MNG": ("image", "漫画"),
    "SCM": ("image", "剧画"),
    "ICG": ("image", "CG·插画"),
    "WBT": ("image", "条漫"),
    "VCM": ("image", "有声漫画"),
    "SOU": ("audio", "声音·ASMR"),
    "MUS": ("audio", "音乐"),
    "MOV": ("video", "视频"),
    "NRE": ("other", "小说"),
    "PBC": ("other", "杂志·出版物"),
    "TOL": ("other", "工具"),
    "IMT": ("other", "图像素材"),
    "AMT": ("other", "音频素材"),
    "ET3": ("other", "其他"),
}
_TITLE_LOCALES = ("zh_CN", "zh_TW", "ja_JP", "en_US", "ko_KR")
_IMAGE_SUFFIXES = (".dlsite.jp", ".dlsite.com")
_SITE_ID = re.compile(r"[a-z0-9_-]{1,32}")


@dataclass(frozen=True)
class OwnedWork:
    source_work_id: str
    acquired_at: str | None


def _localized(value: Any) -> tuple[str | None, tuple[str, ...]]:
    """The preferred name, and every other spelling so that all of them can be searched."""
    if isinstance(value, str):
        text = value.strip()
        return (text, ()) if text else (None, ())
    if not isinstance(value, Mapping):
        return None, ()
    names = {
        str(locale): str(text).strip()
        for locale, text in value.items()
        if isinstance(text, str) and text.strip()
    }
    if not names:
        return None, ()
    preferred = next((names[locale] for locale in _TITLE_LOCALES if locale in names), None)
    chosen = preferred or next(iter(names.values()))
    others = tuple(dict.fromkeys(name for name in names.values() if name != chosen))
    return chosen, others


def cover_address(value: Any) -> str | None:
    """Only https addresses on the platform's image hosts are ever kept."""
    if not isinstance(value, str) or not value.strip():
        return None
    url = value.strip()
    if url.startswith("//"):
        url = f"https:{url}"
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme != "https" or not any(host.endswith(suffix) for suffix in _IMAGE_SUFFIXES):
        return None
    return url


def _tags(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    names = [
        str(item["name"]).strip()
        for item in value
        if isinstance(item, Mapping) and isinstance(item.get("name"), str) and item["name"].strip()
    ]
    return tuple(dict.fromkeys(names))


def _size(value: Any) -> int | None:
    """Bytes, when it is a real positive number. Anything else is not reported."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value)
    return value if isinstance(value, int) and value > 0 else None


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def source_url(source_work_id: str, site_id: Any = None) -> str:
    site = site_id if isinstance(site_id, str) and _SITE_ID.fullmatch(site_id) else "home"
    return f"https://www.dlsite.com/{site}/work/=/product_id/{source_work_id}.html"


def _upgraded(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def map_work(raw: Any) -> SourceMetadata | None:
    """None means the record is unusable: no identity or no title. The ID stays opaque."""
    if not isinstance(raw, Mapping):
        return None
    work_id = raw.get("workno")
    if not isinstance(work_id, str) or not work_id.strip():
        return None
    title, other_titles = _localized(raw.get("name"))
    if title is None:
        title, other_titles = _localized(raw.get("work_name"))
    if title is None:
        return None
    code = _text(raw.get("work_type"))
    kind, genre = WORK_TYPES.get(code or "", ("other", None))
    maker = raw.get("maker")
    maker_name = _localized(maker.get("name"))[0] if isinstance(maker, Mapping) else None
    files = raw.get("work_files")
    cover = cover_address(files.get("main")) if isinstance(files, Mapping) else None
    return SourceMetadata(
        source_id="dlsite",
        source_work_id=work_id.strip(),
        title=title,
        alt_titles=other_titles,
        kind=kind,
        raw_kind=code,
        maker=maker_name or _text(raw.get("author_name")),
        genre=genre,
        release_date=_text(raw.get("regist_date")),
        cover_ref=cover,
        tags=_tags(raw.get("tags")),
        source_url=source_url(work_id.strip(), raw.get("site_id")),
        can_download=raw["downloadable"] if isinstance(raw.get("downloadable"), bool) else None,
        upgraded_at=_upgraded(raw.get("upgrade_date")),
        download_size=_size(raw.get("content_size")),
    )


def owned_works(raw: Any) -> list[OwnedWork] | None:
    """The list of owned IDs, deduplicated in order. None means it is not a list at all."""
    if not isinstance(raw, list):
        return None
    seen: dict[str, OwnedWork] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        work_id = item.get("workno")
        if isinstance(work_id, str) and work_id.strip() and work_id.strip() not in seen:
            seen[work_id.strip()] = OwnedWork(work_id.strip(), _text(item.get("sales_date")))
    return list(seen.values())
