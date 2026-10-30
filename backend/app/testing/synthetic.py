"""Synthetic works for the isolated test library. Never runs on normal startup.

Every title and maker is invented. Fixed seed, so runs are reproducible.
"""

import random
from dataclasses import dataclass, replace

from sqlalchemy import Engine

from app.repositories.works import (
    SourceMetadata,
    WorkFile,
    replace_work_files,
    set_visibility,
    upsert_source_metadata,
)

SEED = 0x41544C41
PRIVATE_SENTINELS = {
    "private": "PRIVATE-SENTINEL-不应出现",
    "hidden": "HIDDEN-SENTINEL-不应出现",
    "quarantined": "QUARANTINE-SENTINEL-不应出现",
}
LONG_TITLE = (
    "星屑の図書館と夜明けを待つ旅人たち The Very Long Journey Through the Archive of "
    "Forgotten Constellations 第二巻・完全版"
)
_ADJECTIVES = ("远航", "薄暮", "星砂", "雾灯", "群岛", "回声", "纸鹤", "潮汐", "余烬", "晨歌")
_NOUNS = ("档案", "旅人", "灯塔", "花园", "信使", "钟楼", "列车", "航线", "庭院", "地图")
_MAKERS = ("示例工作室", "虚构社团", "Atlas Samples", "合成制作组")
_GAME_GENRES = ("RPG", "冒险", "解谜", "模拟", "动作")
_MEDIA_GENRES = ("短篇", "插画集", "环境音", "有声剧")


@dataclass(frozen=True)
class Sample:
    id: str
    metadata: SourceMetadata
    visibility: str = "normal"
    files: tuple[WorkFile, ...] = ()


def _at(rng: random.Random) -> str:
    return (
        f"2026-{rng.randint(1, 10):02d}-{rng.randint(1, 28):02d}"
        f"T{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:00+00:00"
    )


def _generated(index: int, rng: random.Random) -> Sample:
    steam = index % 3 != 2
    kind = "game" if steam or index % 6 == 2 else ("image", "video", "audio", "other")[index % 4]
    title = f"{rng.choice(_ADJECTIVES)}{rng.choice(_NOUNS)} {index}"
    is_game = kind == "game"
    tracked = steam and index % 7 != 3
    playtime = rng.choice((0, rng.randint(1, 59), rng.randint(60, 9000))) if tracked else None
    achievements_total = rng.randint(10, 60) if steam and index % 5 == 0 else None
    metadata = SourceMetadata(
        source_id="steam" if steam else "dlsite",
        source_work_id=str(100000 + index) if steam else f"RJ{100000 + index}",
        kind=kind,
        raw_kind=None if steam else ("RPG" if is_game else ("ICG", "MOV", "SOU", "ET3")[index % 4]),
        title=title,
        subtitle=None if index % 4 else "合成样本",
        maker=None if index % 17 == 5 else rng.choice(_MAKERS),
        genre=rng.choice(_GAME_GENRES if is_game else _MEDIA_GENRES),
        description=None
        if index % 19 == 7
        else f"《{title}》是用于测试的合成条目，不对应真实作品。",
        release_date=None
        if index % 13 == 6
        else f"20{rng.randint(10, 26)}-0{rng.randint(1, 9)}-15",
        cover_ref=None if index % 11 == 2 else f"synthetic:{index}",
        tags=("合成样本", rng.choice(("单人", "短篇", "氛围"))),
        playtime_minutes=playtime,
        last_used_at=_at(rng) if index % 3 == 0 else None,
        achievements_unlocked=rng.randint(0, achievements_total) if achievements_total else None,
        achievements_total=achievements_total,
        local_state=("unknown", "available", "absent")[index % 3],
        can_download=None if steam else index % 4 != 1,
        can_extract=None if steam else index % 2 == 0,
        official_viewer_only=None if steam else index % 4 == 1,
    )
    files = (
        ()
        if steam
        else (
            WorkFile(
                version="1.0",
                size_bytes=None if index % 9 == 0 else rng.randint(10**6, 4 * 10**9),
                format="zip",
                availability="downloadable",
                download_state="not_downloaded",
                extract_state="not_extracted",
            ),
        )
    )
    return Sample(id=f"syn-{index:05d}", metadata=metadata, files=files)


def _curated() -> list[Sample]:
    """Named edge cases the tests look up directly."""
    game = SourceMetadata(
        source_id="steam",
        source_work_id="1001",
        kind="game",
        title="同名样本：夜行灯塔",
        maker="示例工作室",
        genre="冒险",
        description="跨来源身份测试：与 DLsite 条目来源编号相同、标题相同。",
        cover_ref="synthetic:1",
        tags=("合成样本",),
        playtime_minutes=725,
        last_used_at="2026-10-28T12:00:00+00:00",
        achievements_unlocked=7,
        achievements_total=20,
        local_state="available",
    )
    dlsite = SourceMetadata(
        source_id="dlsite",
        source_work_id="1001",
        kind="audio",
        raw_kind="SOU",
        title="同名样本：夜行灯塔",
        maker="虚构社团",
        genre="环境音",
        description="跨来源身份测试：不得与 Steam 条目合并。",
        cover_ref="synthetic:2",
        tags=("合成样本",),
        last_used_at="2026-10-27T12:00:00+00:00",
        local_state="absent",
        can_download=True,
        can_extract=True,
        official_viewer_only=False,
    )
    multipart = SourceMetadata(
        source_id="dlsite",
        source_work_id="RJ900001",
        kind="game",
        raw_kind="RPG",
        title="多文件样本：群岛航线",
        maker="虚构社团",
        genre="RPG",
        description="一个作品对应多个语言版本与分卷，不是多个作品。",
        cover_ref="synthetic:3",
        tags=("合成样本", "多文件"),
        local_state="absent",
        can_download=True,
        can_extract=True,
        official_viewer_only=False,
    )
    unknown = SourceMetadata(
        source_id="dlsite",
        source_work_id="RJ900002",
        raw_kind="ZZZ",
        title="未知字段样本",
    )
    return [
        Sample("syn-steam-1001", game),
        Sample("syn-dlsite-1001", dlsite),
        Sample(
            "syn-multipart",
            multipart,
            files=(
                WorkFile(
                    label="日文版 第 1 卷",
                    version="1.2",
                    language="JPN",
                    part_index=1,
                    part_count=2,
                    size_bytes=2_000_000_000,
                    format="rar",
                    availability="downloadable",
                    download_state="not_downloaded",
                    extract_state="not_extracted",
                ),
                WorkFile(
                    label="日文版 第 2 卷",
                    version="1.2",
                    language="JPN",
                    part_index=2,
                    part_count=2,
                    size_bytes=1_500_000_000,
                    format="rar",
                    availability="downloadable",
                    download_state="not_downloaded",
                    extract_state="not_extracted",
                ),
                WorkFile(
                    label="中文版",
                    version="1.0",
                    language="CHI_HANS",
                    size_bytes=None,
                    format=None,
                    availability="unknown",
                ),
            ),
        ),
        Sample("syn-unknown", unknown),
        Sample(
            "syn-long-title",
            replace(dlsite, source_work_id="RJ900003", title=LONG_TITLE, cover_ref=None),
        ),
        *(
            Sample(
                f"syn-{visibility}",
                replace(
                    game,
                    source_work_id=f"SENTINEL-{visibility}",
                    title=title,
                    maker=f"{visibility}-SENTINEL-MAKER",
                    genre="SENTINEL-GENRE",
                ),
                visibility=visibility,
            )
            for visibility, title in PRIVATE_SENTINELS.items()
        ),
    ]


def build_samples(size: int) -> list[Sample]:
    """`size` counts ordinary works; the three sentinels come on top."""
    rng = random.Random(SEED)
    curated = _curated()
    ordinary = sum(sample.visibility == "normal" for sample in curated)
    return [*curated, *(_generated(index, rng) for index in range(max(0, size - ordinary)))]


def seed(engine: Engine, size: int) -> int:
    samples = build_samples(size)
    with engine.begin() as connection:
        for sample in samples:
            work_id = upsert_source_metadata(connection, sample.metadata, work_id=sample.id)
            set_visibility(connection, work_id, sample.visibility)
            if sample.files:
                replace_work_files(connection, work_id, sample.files)
    return len(samples)
