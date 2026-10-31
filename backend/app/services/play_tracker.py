"""How long the user has played, recorded by Atlas for platforms that do not report it.

One record per session, marked with where it came from, in the shape a platform's own figures can
later join: a running total and a last-played time on the work, as Steam reports them, and sessions
beneath. Time counts while Atlas can see the game running, and a suspended computer does not count.
Only games started from Atlas are seen. A time that had to be estimated is marked, never presented
as measured.
"""

import logging
import threading
import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, Row, func, select, update

from app.adapters.system.process_job import ProcessWatch, RunningGame
from app.api import models
from app.db.engine import writing
from app.db.schema import personal_records, play_sessions, works
from app.repositories.works import ORDINARY, get_ordinary_work

logger = logging.getLogger("atlas")

SOURCE_ATLAS = "atlas"
MIN_SECONDS = 10.0
_POLL_SECONDS = 5.0
_SAVE_EVERY = 30.0
_MAX_SESSIONS_SHOWN = 30
_MAX_MONTHS = 36
_TOP_PER_MONTH = 5
_RECENT_DAYS = 14


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _parse(text: str) -> datetime:
    return datetime.fromisoformat(text)


def month_shares(start: datetime, seconds: float) -> dict[str, float]:
    """A session over midnight on the last of the month counts in both months, in local time."""
    shares: dict[str, float] = {}
    moment = start.astimezone()
    left = seconds
    while left > 0:
        month_end = (
            moment.replace(year=moment.year + 1, month=1, day=1, hour=0, minute=0, second=0)
            if moment.month == 12
            else moment.replace(month=moment.month + 1, day=1, hour=0, minute=0, second=0)
        ).replace(microsecond=0)
        here = min(left, max((month_end - moment).total_seconds(), 0.001))
        key = moment.strftime("%Y-%m")
        shares[key] = shares.get(key, 0.0) + here
        left -= here
        moment = month_end
    return shares


class PlayTracker:
    def __init__(
        self,
        engine: Engine,
        *,
        reopen: Callable[[str], RunningGame | None] = ProcessWatch.reopen,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        poll_seconds: float = _POLL_SECONDS,
        min_seconds: float = MIN_SECONDS,
    ) -> None:
        self._engine = engine
        self._reopen = reopen
        self._now = now
        self._poll = poll_seconds
        self._min = min_seconds
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}
        self.on_exit: Callable[[str, Path | None], None] | None = None

    # --- following a game ---

    def recover(self) -> None:
        """A session Atlas was following when it closed: the game may still be running. If not,
        it ended some time since the last note, which is all that can be counted."""
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(play_sessions).where(play_sessions.c.state == "running")
            ).all()
        for row in rows:
            watch = self._reopen(row.watch_name) if row.watch_name else None
            if watch is not None and watch.running():
                self._follow(row.id, row.work_id, watch, float(row.seconds), None)
            else:
                if watch is not None:
                    watch.close()
                self._finish(row.id, row.work_id, float(row.seconds), "unknown", row.heartbeat_at)

    def shutdown(self) -> None:
        """Leaves the record open: the game may well outlive Atlas."""
        self._stop.set()
        for thread in list(self._threads.values()):
            thread.join(timeout=10)

    def started(
        self, work_id: str, copy_id: str, watch: RunningGame | None, program: Path | None
    ) -> None:
        if watch is None:
            return
        with self._engine.connect() as connection:
            already = connection.execute(
                select(play_sessions.c.id).where(
                    play_sessions.c.work_id == work_id, play_sessions.c.state == "running"
                )
            ).first()
        if already is not None:
            # A second window of a game already being timed is not more play.
            watch.close()
            return
        session_id = uuid.uuid4().hex
        moment = _iso(self._now())
        with writing(self._engine).begin() as connection:
            connection.execute(
                play_sessions.insert().values(
                    id=session_id,
                    work_id=work_id,
                    copy_id=copy_id,
                    source=SOURCE_ATLAS,
                    started_at=moment,
                    heartbeat_at=moment,
                    seconds=0.0,
                    state="running",
                    watch_name=watch.name,
                )
            )
            connection.execute(
                update(works).where(works.c.id == work_id).values(last_used_at=moment)
            )
        self._follow(session_id, work_id, watch, 0.0, program)

    def _follow(
        self,
        session_id: str,
        work_id: str,
        watch: RunningGame,
        counted: float,
        program: Path | None,
    ) -> None:
        thread = threading.Thread(
            target=self._loop,
            args=(session_id, work_id, watch, counted, program),
            name="play-tracker",
            daemon=True,
        )
        self._threads[session_id] = thread
        thread.start()

    def _loop(
        self,
        session_id: str,
        work_id: str,
        watch: RunningGame,
        counted: float,
        program: Path | None,
    ) -> None:
        """Adds up what passes between looks, with a limit: a gap far longer than the interval is
        a sleeping computer, not play."""
        last = time.monotonic()
        last_clock = self._now()
        saved = last
        try:
            while not self._stop.wait(self._poll):
                moment = time.monotonic()
                clock = self._now()
                gap = min(moment - last, (clock - last_clock).total_seconds())
                counted += min(max(gap, 0.0), self._poll * 6)
                last, last_clock = moment, clock
                if not watch.running():
                    self._finish(session_id, work_id, counted, "exit", _iso(clock))
                    if self.on_exit is not None:
                        self.on_exit(work_id, program)
                    return
                if moment - saved >= _SAVE_EVERY:
                    saved = moment
                    self._note(session_id, counted, _iso(clock))
            self._note(session_id, counted, _iso(self._now()))
        except Exception as error:  # noqa: BLE001 - the game goes on; type only.
            logger.error("play tracking stopped: %s", type(error).__name__)
        finally:
            watch.close()
            self._threads.pop(session_id, None)

    def _note(self, session_id: str, counted: float, moment: str) -> None:
        with writing(self._engine).begin() as connection:
            connection.execute(
                update(play_sessions)
                .where(play_sessions.c.id == session_id)
                .values(seconds=counted, heartbeat_at=moment)
            )

    def _finish(
        self, session_id: str, work_id: str, counted: float, ended_by: str, moment: str
    ) -> None:
        with writing(self._engine).begin() as connection:
            connection.execute(
                update(play_sessions)
                .where(play_sessions.c.id == session_id)
                .values(
                    seconds=counted,
                    heartbeat_at=moment,
                    ended_at=moment,
                    ended_by=ended_by,
                    state="finished",
                )
            )
            total = connection.execute(
                select(func.coalesce(func.sum(play_sessions.c.seconds), 0.0)).where(
                    play_sessions.c.work_id == work_id,
                    play_sessions.c.state == "finished",
                    play_sessions.c.seconds >= self._min,
                )
            ).scalar_one()
            values: dict[str, Any] = {"playtime_minutes": int(total // 60)}
            if counted >= self._min:
                values["last_used_at"] = moment
            connection.execute(update(works).where(works.c.id == work_id).values(**values))

    # --- reading ---

    def _counted(self, rows: list[Row[Any]]) -> list[Row[Any]]:
        return [row for row in rows if row.state == "running" or row.seconds >= self._min]

    def work(self, work_id: str) -> models.WorkPlayOut:
        with self._engine.connect() as connection:
            work = get_ordinary_work(connection, work_id)
            rows = list(
                connection.execute(
                    select(play_sessions)
                    .where(play_sessions.c.work_id == work_id)
                    .order_by(play_sessions.c.started_at.desc())
                )
            )
        counted = self._counted(rows)
        months: dict[str, float] = defaultdict(float)
        for row in counted:
            for month, seconds in month_shares(_parse(row.started_at), row.seconds).items():
                months[month] += seconds
        cutoff = self._now() - timedelta(days=_RECENT_DAYS)
        running = next((row for row in rows if row.state == "running"), None)
        return models.WorkPlayOut(
            running=running is not None,
            running_since=running.started_at if running else None,
            total_seconds=sum(row.seconds for row in counted),
            total_minutes=work.playtime_minutes,
            last_played_at=work.last_used_at,
            recent_seconds=sum(row.seconds for row in counted if _parse(row.started_at) >= cutoff),
            sessions=[
                models.PlaySessionOut(
                    id=row.id,
                    started_at=row.started_at,
                    ended_at=row.ended_at,
                    seconds=row.seconds,
                    source=row.source,
                    estimated=row.ended_by == "unknown",
                    running=row.state == "running",
                )
                for row in counted[:_MAX_SESSIONS_SHOWN]
            ],
            months=[
                models.PlayMonthOut(month=month, seconds=seconds, sessions=0, top=[])
                for month, seconds in sorted(months.items(), reverse=True)
            ],
        )

    def stats(self, months: int) -> models.PlayStatsOut:
        """Across the library, of what ordinary views may show: a hidden work does not appear, even
        as a part of a total."""
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(play_sessions, works.c.title, works.c.source_id)
                .join(works, works.c.id == play_sessions.c.work_id)
                .join(personal_records, personal_records.c.work_id == works.c.id)
                .where(ORDINARY)
                .order_by(play_sessions.c.started_at.desc())
            ).all()
        counted = self._counted(list(rows))
        now = self._now().astimezone()
        wanted: list[str] = []
        year, month = now.year, now.month
        for _index in range(min(max(months, 1), _MAX_MONTHS)):
            wanted.append(f"{year:04d}-{month:02d}")
            year, month = (year - 1, 12) if month == 1 else (year, month - 1)
        totals: dict[str, float] = defaultdict(float)
        per_work: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        sessions: dict[str, int] = defaultdict(int)
        titles: dict[str, str] = {}
        for row in counted:
            titles[row.work_id] = row.title
            for key, seconds in month_shares(_parse(row.started_at), row.seconds).items():
                totals[key] += seconds
                per_work[key][row.work_id] += seconds
                sessions[key] += 1
        recent: dict[str, Row[Any]] = {}
        for row in counted:
            recent.setdefault(row.work_id, row)
        cutoff = self._now() - timedelta(days=_RECENT_DAYS)
        return models.PlayStatsOut(
            total_seconds=sum(row.seconds for row in counted),
            recent_seconds=sum(row.seconds for row in counted if _parse(row.started_at) >= cutoff),
            months=[
                models.PlayMonthOut(
                    month=key,
                    seconds=totals.get(key, 0.0),
                    sessions=sessions.get(key, 0),
                    top=[
                        models.PlayWorkShare(
                            work_id=work_id, title=titles[work_id], seconds=seconds
                        )
                        for work_id, seconds in sorted(
                            per_work.get(key, {}).items(), key=lambda item: -item[1]
                        )[:_TOP_PER_MONTH]
                    ],
                )
                for key in wanted
            ],
            recent=[
                models.PlayRecentOut(
                    work_id=row.work_id,
                    title=row.title,
                    platform=row.source_id,
                    last_played_at=row.ended_at or row.started_at,
                    running=row.state == "running",
                )
                for row in list(recent.values())[:10]
            ],
        )
