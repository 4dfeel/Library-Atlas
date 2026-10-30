"""Dashboard aggregation over works that already passed the visibility policy.

Same rules as the frontend's demo `selectDashboard`, so both modes count the same way.
Pure: the caller supplies the already-filtered rows and the date seed.
"""

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

Scope = Literal["all", "games", "steam", "dlsite-games", "dlsite-media"]
KINDS = ("game", "image", "video", "audio", "other")
_BUCKETS: tuple[tuple[str, int, float], ...] = (
    ("< 1 小时", 0, 60),
    ("1–10 小时", 60, 600),
    ("10–50 小时", 600, 3000),
    ("50–100 小时", 3000, 6000),
    ("100 小时以上", 6000, float("inf")),
)
UNCATEGORIZED = "未分类"


@dataclass(frozen=True)
class WorkFacts:
    id: str
    platform: str
    kind: str
    genre: str | None
    status: str
    local: bool | None
    favorite: bool
    has_cover: bool
    playtime_minutes: int | None
    last_used_at: str | None


@dataclass(frozen=True)
class DashboardPicks:
    featured: list[str]
    recent: list[str]
    most_played: list[str]
    recommendations: list[tuple[str, list[str]]]


def in_scope(work: WorkFacts, scope: Scope) -> bool:
    match scope:
        case "all":
            return True
        case "games":
            return work.kind == "game"
        case "steam":
            return work.platform == "steam"
        case "dlsite-games":
            return work.platform == "dlsite" and work.kind == "game"
        case "dlsite-media":
            return work.platform == "dlsite" and work.kind != "game"


def _hash(text: str) -> float:
    """FNV-1a: stable across runs, unlike Python's salted `hash`."""
    value = 0x811C9DC5
    for character in text:
        value ^= ord(character)
        value = (value * 0x01000193) & 0xFFFFFFFF
    return value / 4294967296


def _recommend(pool: Iterable[WorkFacts], seed: str) -> list[tuple[str, list[str]]]:
    scored: list[tuple[float, str, list[str]]] = []
    for work in pool:
        if work.status not in ("unplayed", "paused"):
            continue
        reasons: list[str] = []
        score = _hash(f"{seed}:{work.id}")
        if work.local:
            score += 1.2
            reasons.append("已安装" if work.platform == "steam" else "已下载")
        if work.favorite:
            score += 1
            reasons.append("你收藏过")
        reasons.append("上次搁置，可以接着来" if work.status == "paused" else "还没开始")
        scored.append((-score, work.id, reasons))
    return [(work_id, reasons) for _, work_id, reasons in sorted(scored)[:3]]


def _recent_key(work: WorkFacts) -> tuple[str, str]:
    return (work.last_used_at or "", work.id)


def _by_recent(works: Iterable[WorkFacts]) -> list[WorkFacts]:
    # Newest first, ties by ascending ID: stable sort on the secondary key first.
    ordered = sorted(works, key=lambda work: work.id)
    return sorted(ordered, key=lambda work: work.last_used_at or "", reverse=True)


def aggregate(
    visible: Sequence[WorkFacts], scope: Scope, seed: str
) -> tuple[dict[str, object], DashboardPicks]:
    works = [work for work in visible if in_scope(work, scope)]
    games = [work for work in works if work.kind == "game"]
    non_games = [work for work in works if work.kind != "game"]
    has_games = scope != "dlsite-media"
    played = [work for work in games if (work.playtime_minutes or 0) > 0]

    featured = sorted(
        _by_recent(work for work in works if work.has_cover),
        key=lambda work: not work.favorite,
    )[:8]
    most_played = sorted(played, key=lambda work: (-(work.playtime_minutes or 0), work.id))[:5]
    genres = Counter(work.genre or UNCATEGORIZED for work in games)
    backlog = Counter(work.status for work in (games if has_games else works))

    def source(platform: str) -> dict[str, int]:
        entries = [work for work in visible if work.platform == platform]
        return {
            "works": len(entries),
            "games": sum(work.kind == "game" for work in entries),
            "local": sum(work.local is True for work in entries),
        }

    summary: dict[str, object] = {
        "scope": scope,
        "has_games": has_games,
        "totals": {
            "works": len(works),
            "games": len(games),
            "played_games": len(played),
            "unstarted_games": sum(work.status == "unplayed" for work in games),
            "unknown_playtime_games": sum(work.playtime_minutes is None for work in games),
            "playtime_minutes": sum(work.playtime_minutes or 0 for work in games),
            "non_games": len(non_games),
            "used_non_games": sum(work.last_used_at is not None for work in non_games),
            "local": sum(work.local is True for work in works),
            "favorites": sum(work.favorite for work in works),
        },
        "playtime_buckets": [
            {
                "label": label,
                "count": sum(low <= (work.playtime_minutes or 0) < high for work in played),
            }
            for label, low, high in _BUCKETS
        ],
        "genres": [
            {"genre": genre, "count": count}
            for genre, count in sorted(genres.items(), key=lambda item: (-item[1], item[0]))
        ],
        "kinds": [
            {
                "kind": kind,
                "steam": sum(w.kind == kind and w.platform == "steam" for w in works),
                "dlsite": sum(w.kind == kind and w.platform == "dlsite" for w in works),
            }
            for kind in KINDS
        ],
        "backlog": {
            status: backlog[status] for status in ("unplayed", "playing", "completed", "paused")
        },
        "sources": {"steam": source("steam"), "dlsite": source("dlsite")},
    }
    picks = DashboardPicks(
        featured=[work.id for work in featured],
        recent=[work.id for work in _by_recent(w for w in works if w.last_used_at)][:12],
        most_played=[work.id for work in most_played],
        recommendations=_recommend(games if has_games else non_games, seed),
    )
    return summary, picks
