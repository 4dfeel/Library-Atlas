"""Recording play, through the real API and database, with a real job following real processes in
one test and a stand-in everywhere else. Every program started here is made up on the spot."""

import subprocess
import sys
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.adapters.system.process_job import ProcessWatch
from app.core.config import Settings
from app.db.schema import personal_records, play_sessions, works
from app.services.play_tracker import PlayTracker, month_shares
from tests.conftest import client_for
from tests.test_downloads import Rig, engine_of, prepare, work_ids


class Fake:
    name = "fake-job"

    def __init__(self) -> None:
        self.alive = True
        self.closed = False

    def running(self) -> bool:
        return self.alive

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def rig(settings: Settings, tmp_path: Path) -> Rig:
    return Rig(settings, tmp_path)


@pytest.fixture
def api(settings: Settings, rig: Rig) -> Iterator[TestClient]:
    with client_for(settings) as client:
        prepare(client, rig)
        yield client


def tracker_of(client: TestClient, **overrides: Any) -> PlayTracker:
    tracker: PlayTracker = client.app.state.service.play  # type: ignore[attr-defined]
    tracker._poll = 0.01
    tracker._min = overrides.get("min_seconds", 0.0)
    return tracker


def session(
    client: TestClient, work_id: str, seconds: float, started: datetime, **more: Any
) -> None:
    with engine_of(client).begin() as connection:
        connection.execute(
            play_sessions.insert().values(
                id=f"s{time.monotonic_ns()}",
                work_id=work_id,
                copy_id="copy",
                source="atlas",
                started_at=started.isoformat(),
                heartbeat_at=started.isoformat(),
                ended_at=(started + timedelta(seconds=seconds)).isoformat(),
                ended_by=more.get("ended_by", "exit"),
                seconds=seconds,
                state="finished",
            )
        )


def wait_for(check: Any) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.01)
    raise AssertionError("did not happen")


def play_of(client: TestClient, work_id: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/works/{work_id}/play")
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


# --- following ---


def test_a_session_is_recorded_from_start_to_exit_and_reaches_the_work(api: TestClient) -> None:
    work = work_ids(api)[0]
    tracker = tracker_of(api)
    exited: list[str] = []
    tracker.on_exit = lambda work_id, program: exited.append(work_id)
    game = Fake()
    tracker.started(work["id"], "copy", game, None)
    wait_for(lambda: play_of(api, work["id"])["running"])
    assert play_of(api, work["id"])["sessions"][0]["running"] is True
    game.alive = False
    wait_for(lambda: exited)
    data = play_of(api, work["id"])
    assert data["running"] is False
    assert data["sessions"][0]["endedAt"]
    assert data["sessions"][0]["source"] == "atlas"
    assert data["lastPlayedAt"]
    assert game.closed is True


def test_totals_land_where_the_library_and_dashboard_read_them(api: TestClient) -> None:
    work = work_ids(api)[0]
    tracker = tracker_of(api)
    start = datetime.now(UTC)
    session(api, work["id"], 3600, start - timedelta(hours=2))
    tracker._finish("none", work["id"], 0.0, "exit", start.isoformat())
    listed = api.get(f"/api/v1/works/{work['id']}").json()
    assert listed["playtimeMinutes"] == 60
    assert listed["lastPlayedAt"]


def test_a_launch_that_comes_to_nothing_does_not_count(api: TestClient) -> None:
    work = work_ids(api)[0]
    tracker = tracker_of(api, min_seconds=10.0)
    start = datetime.now(UTC)
    session(api, work["id"], 2, start)
    tracker._finish("none", work["id"], 2.0, "exit", start.isoformat())
    data = play_of(api, work["id"])
    assert data["sessions"] == []
    assert data["totalSeconds"] == 0


def test_a_second_launch_of_a_running_game_is_not_more_play(api: TestClient) -> None:
    work = work_ids(api)[0]
    tracker = tracker_of(api)
    first, second = Fake(), Fake()
    tracker.started(work["id"], "copy", first, None)
    tracker.started(work["id"], "copy", second, None)
    assert second.closed is True
    with engine_of(api).connect() as connection:
        assert len(connection.execute(select(play_sessions)).all()) == 1
    first.alive = False


def test_no_way_to_follow_it_means_no_record_not_a_wrong_one(api: TestClient) -> None:
    work = work_ids(api)[0]
    tracker_of(api).started(work["id"], "copy", None, None)
    assert play_of(api, work["id"])["sessions"] == []


def test_a_sleeping_computer_does_not_count_as_play(api: TestClient) -> None:
    work = work_ids(api)[0]
    tracker = tracker_of(api)
    moments = [datetime.now(UTC) + timedelta(hours=8 * index) for index in range(1000)]
    tracker._now = lambda: moments.pop(0) if len(moments) > 1 else moments[0]
    game = Fake()
    tracker.started(work["id"], "copy", game, None)
    time.sleep(0.05)
    game.alive = False
    wait_for(lambda: not play_of(api, work["id"])["running"])
    assert play_of(api, work["id"])["sessions"][0]["seconds"] < 5


def test_a_game_still_running_after_atlas_restarts_is_followed_again(api: TestClient) -> None:
    """As it stands right after a restart: a session left open, and its job still there."""
    work = work_ids(api)[0]
    start = datetime.now(UTC) - timedelta(hours=1)
    with engine_of(api).begin() as connection:
        connection.execute(
            play_sessions.insert().values(
                id="left",
                work_id=work["id"],
                copy_id="copy",
                source="atlas",
                started_at=start.isoformat(),
                heartbeat_at=start.isoformat(),
                seconds=600.0,
                state="running",
                watch_name="still-there",
            )
        )
    game = Fake()
    tracker = tracker_of(api)
    tracker._reopen = lambda name: game
    tracker.recover()
    assert play_of(api, work["id"])["running"] is True
    game.alive = False
    wait_for(lambda: not play_of(api, work["id"])["running"])
    held = play_of(api, work["id"])["sessions"][0]
    assert held["estimated"] is False
    assert held["seconds"] >= 600


def test_a_game_that_ended_while_atlas_was_away_is_marked_as_estimated(
    settings: Settings, rig: Rig
) -> None:
    with client_for(settings) as client:
        prepare(client, rig)
        work = work_ids(client)[0]
        start = datetime.now(UTC) - timedelta(hours=1)
        with engine_of(client).begin() as connection:
            connection.execute(
                play_sessions.insert().values(
                    id="left",
                    work_id=work["id"],
                    copy_id="copy",
                    source="atlas",
                    started_at=start.isoformat(),
                    heartbeat_at=start.isoformat(),
                    seconds=600.0,
                    state="running",
                    watch_name="gone",
                )
            )
    with client_for(settings) as client:
        data = play_of(client, work["id"])
        assert data["running"] is False
        assert data["sessions"][0]["estimated"] is True
        assert data["sessions"][0]["seconds"] == 600


def test_a_sync_does_not_wipe_what_was_recorded(api: TestClient) -> None:
    work = work_ids(api)[0]
    with engine_of(api).begin() as connection:
        connection.execute(
            update(works)
            .where(works.c.id == work["id"])
            .values(playtime_minutes=90, last_used_at="2026-01-01T00:00:00+00:00")
        )
    assert api.post("/api/v1/sources/dlsite/sync").status_code == 200
    wait_for(
        lambda: (api.get("/api/v1/sources/dlsite/sync").json().get("job") or {}).get("state")
        == "succeeded"
    )
    listed = api.get(f"/api/v1/works/{work['id']}").json()
    assert listed["playtimeMinutes"] == 90
    assert listed["lastPlayedAt"].startswith("2026-01-01")


# --- the real thing ---


def test_a_real_job_follows_past_a_launcher_that_quits(tmp_path: Path) -> None:
    pytest.importorskip("_winapi")
    child = tmp_path / "child.py"
    child.write_text("import time\ntime.sleep(2.5)\n")
    launcher = tmp_path / "launcher.py"
    launcher.write_text(
        f"import subprocess, sys\nsubprocess.Popen([sys.executable, {str(child)!r}])\n"
    )
    process = subprocess.Popen([sys.executable, str(launcher)])
    watch = ProcessWatch.follow(process, f"LibraryAtlasTest-{time.monotonic_ns()}")
    assert watch.name is not None
    process.wait(timeout=10)
    # The launcher has gone. Its child is what the user is playing.
    assert watch.running() is True
    again = ProcessWatch.reopen(watch.name)
    assert again is not None
    assert again.running() is True
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and watch.running():
        time.sleep(0.05)
    assert watch.running() is False
    again.close()
    watch.close()


def test_a_job_that_no_longer_exists_says_so() -> None:
    assert ProcessWatch.reopen(f"LibraryAtlasTest-none-{time.monotonic_ns()}") is None


# --- months ---


def test_a_session_across_midnight_counts_in_both_months() -> None:
    local = datetime(2026, 3, 31, 23, 30).astimezone()
    shares = month_shares(local, 3600)
    assert shares == {"2026-03": pytest.approx(1800), "2026-04": pytest.approx(1800)}


def test_a_session_across_new_year_counts_in_both_years() -> None:
    local = datetime(2026, 12, 31, 23, 59).astimezone()
    assert set(month_shares(local, 120)) == {"2026-12", "2027-01"}


def test_monthly_figures_and_the_two_week_figure(api: TestClient) -> None:
    one, two = work_ids(api)[:2]
    tracker_of(api, min_seconds=10.0)
    now = datetime.now(UTC)
    session(api, one["id"], 3600, now - timedelta(days=1))
    session(api, two["id"], 7200, now - timedelta(days=2))
    session(api, one["id"], 1800, now - timedelta(days=70))
    session(api, one["id"], 3, now - timedelta(days=1))
    stats = api.get("/api/v1/play/stats", params={"months": 12}).json()
    assert stats["totalSeconds"] == pytest.approx(12600)
    assert stats["recentSeconds"] == pytest.approx(10800)
    assert len(stats["months"]) == 12
    assert sum(item["seconds"] for item in stats["months"]) == pytest.approx(12600)
    assert stats["recent"][0]["workId"] in (one["id"], two["id"])
    busiest = max(stats["months"], key=lambda item: item["seconds"])
    assert busiest["top"][0]["workId"] == two["id"] or busiest["top"][0]["seconds"] >= 3600
    data = play_of(api, one["id"])
    assert data["recentSeconds"] == pytest.approx(3600)
    assert sum(item["seconds"] for item in data["months"]) == pytest.approx(5400)


@pytest.mark.parametrize("visibility", ["hidden", "private", "quarantined"])
def test_a_hidden_work_does_not_appear_even_in_a_total(api: TestClient, visibility: str) -> None:
    one, two = work_ids(api)[:2]
    now = datetime.now(UTC)
    session(api, one["id"], 3600, now)
    session(api, two["id"], 600, now)
    with engine_of(api).begin() as connection:
        connection.execute(
            update(personal_records)
            .where(personal_records.c.work_id == one["id"])
            .values(visibility=visibility)
        )
    stats = api.get("/api/v1/play/stats").json()
    assert stats["totalSeconds"] == pytest.approx(600)
    assert one["id"] not in str(stats)
    assert api.get(f"/api/v1/works/{one['id']}/play").status_code == 404


def test_starting_a_game_from_atlas_records_a_session(api: TestClient, tmp_path: Path) -> None:
    """With the launch itself replaced: nothing is run here."""
    work = work_ids(api)[0]
    with engine_of(api).begin() as connection:
        connection.execute(update(works).where(works.c.id == work["id"]).values(kind="game"))
    folder = tmp_path / "game"
    folder.mkdir()
    (folder / "Game.exe").write_bytes(b"program")
    copy = api.post(
        f"/api/v1/works/{work['id']}/local-copies", json={"root": str(folder), "entry": "Game.exe"}
    ).json()["copies"][0]
    game = Fake()
    service = api.app.state.service  # type: ignore[attr-defined]
    service.local_copies._launcher = type(
        "Launcher", (), {"launch": staticmethod(lambda program, arguments, working: game)}
    )()
    tracker_of(api)
    assert api.post(f"/api/v1/local-copies/{copy['id']}/launch").status_code == 200
    wait_for(lambda: play_of(api, work["id"])["running"])
    game.alive = False
    wait_for(lambda: not play_of(api, work["id"])["running"])
    assert len(play_of(api, work["id"])["sessions"]) == 1
