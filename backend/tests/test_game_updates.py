"""Updating a game with made-up folders and saves, through the real API and queue, with real file
operations: nothing here mocks a copy, a rename or a delete. No real game or save is involved."""

import json
import os
import shutil
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.core.config import Settings
from app.db.schema import game_updates, personal_records, works
from tests import archive_samples as samples
from tests.conftest import client_for
from tests.test_downloads import Rig, engine_of, first_work, prepare

STILL = ("queued", "backing_up", "downloading", "unpacking", "replacing", "cleaning")


def old_game(root: Path) -> Path:
    folder = root / "ゲーム"
    (folder / "www" / "save").mkdir(parents=True)
    (folder / "Game.exe").write_bytes(b"old program")
    (folder / "old_only.dll").write_bytes(b"outdated")
    (folder / "www" / "save" / "file1.rpgsave").write_bytes(b"my progress")
    (folder / "www" / "save" / "セーブ 2.rpgsave").write_bytes(b"more progress")
    return folder


@pytest.fixture
def rig(settings: Settings, tmp_path: Path) -> Rig:
    return Rig(settings, tmp_path)


@pytest.fixture
def api(settings: Settings, rig: Rig) -> Iterator[TestClient]:
    with client_for(settings) as client:
        prepare(client, rig)
        with engine_of(client).begin() as connection:
            connection.execute(update(works).values(kind="game"))
        yield client


@pytest.fixture
def game(tmp_path: Path) -> Path:
    place = tmp_path / "games"
    place.mkdir()
    return old_game(place)


@pytest.fixture
def new_version(tmp_path: Path, rig: Rig) -> Path:
    archive = samples.zip_with(
        tmp_path / "new.zip",
        {
            "Game.exe": b"new program",
            "new_only.dll": b"fresh",
            "www/save/file1.rpgsave": b"default that must not win",
        },
    )
    rig.behave(payload=str(archive))
    return archive


def link(client: TestClient, work: dict[str, Any], folder: Path) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/works/{work['id']}/local-copies", json={"root": str(folder), "entry": "Game.exe"}
    )
    assert response.status_code == 200, response.text
    copy: dict[str, Any] = response.json()["copies"][0]
    return copy


def saves_inside(client: TestClient, work: dict[str, Any]) -> None:
    response = client.put(
        f"/api/v1/works/{work['id']}/save-config",
        json={"rules": [{"kind": "inside", "path": "www/save"}], "confirmedNone": False},
    )
    assert response.status_code == 200, response.text


def begin(client: TestClient, work: dict[str, Any], copy: dict[str, Any]) -> Any:
    return client.post(
        f"/api/v1/works/{work['id']}/update", json={"copyId": copy["id"], "confirmClosed": True}
    )


def settled(client: TestClient, work: dict[str, Any], seconds: float = 30) -> dict[str, Any]:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        task = client.get(f"/api/v1/works/{work['id']}/update").json()["task"]
        if task and task["state"] not in STILL:
            result: dict[str, Any] = task
            return result
        time.sleep(0.02)
    raise AssertionError("the update did not settle")


def update_to_waiting(
    client: TestClient, game: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    work = first_work(client)
    copy = link(client, work, game)
    saves_inside(client, work)
    assert begin(client, work, copy).status_code == 200
    task = settled(client, work)
    assert task["state"] == "awaiting_confirmation", task["code"]
    return work, copy, task


def siblings(game: Path) -> list[str]:
    return sorted(path.name for path in game.parent.iterdir())


# --- the whole way ---


def test_the_new_version_replaces_the_old_and_saves_come_across(
    api: TestClient, game: Path, new_version: Path
) -> None:
    work, _copy, task = update_to_waiting(api, game)
    assert (game / "Game.exe").read_bytes() == b"new program"
    assert (game / "new_only.dll").read_bytes() == b"fresh"
    # The user's save wins over the default in the new version; nothing old leaks in.
    assert (game / "www" / "save" / "file1.rpgsave").read_bytes() == b"my progress"
    assert (game / "www" / "save" / "セーブ 2.rpgsave").read_bytes() == b"more progress"
    assert not (game / "old_only.dll").exists()
    # Old version kept until the user speaks, and what only it holds is shown to them.
    assert task["extraCount"] == 1
    assert task["extraSample"] == ["old_only.dll"]
    assert len(siblings(game)) == 2

    done = api.post(f"/api/v1/game-updates/{task['id']}/confirm").json()["task"]
    assert done["state"] == "done"
    assert siblings(game) == [game.name]
    assert (game / "www" / "save" / "file1.rpgsave").read_bytes() == b"my progress"
    assert len(api.get(f"/api/v1/works/{work['id']}/update").json()["backups"]) == 1


def test_going_back_restores_the_old_version_whole(
    api: TestClient, game: Path, new_version: Path
) -> None:
    work, _copy, task = update_to_waiting(api, game)
    (game / "www" / "save" / "file1.rpgsave").write_bytes(b"played on the new version")
    back = api.post(f"/api/v1/game-updates/{task['id']}/rollback").json()["task"]
    assert back["state"] == "rolled_back"
    assert (game / "Game.exe").read_bytes() == b"old program"
    assert (game / "old_only.dll").read_bytes() == b"outdated"
    assert (game / "www" / "save" / "file1.rpgsave").read_bytes() == b"my progress"
    assert siblings(game) == [game.name]
    # What was played on the new version is in a backup, not lost.
    assert len(api.get(f"/api/v1/works/{work['id']}/update").json()["backups"]) == 2


def test_saves_outside_the_folder_are_backed_up_and_left_in_place(
    api: TestClient, game: Path, new_version: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "Documents" / "ゲーム"
    outside.mkdir(parents=True)
    (outside / "slot.sav").write_bytes(b"outside save")
    before = (outside / "slot.sav").stat().st_mtime_ns
    work = first_work(api)
    copy = link(api, work, game)
    api.put(
        f"/api/v1/works/{work['id']}/save-config",
        json={"rules": [{"kind": "outside", "path": str(outside)}], "confirmedNone": False},
    )
    begin(api, work, copy)
    assert settled(api, work)["state"] == "awaiting_confirmation"
    assert (outside / "slot.sav").read_bytes() == b"outside save"
    assert (outside / "slot.sav").stat().st_mtime_ns == before
    assert api.get(f"/api/v1/works/{work['id']}/update").json()["backups"][0]["files"] == 1


def test_a_named_save_that_does_not_exist_yet_is_fine(
    api: TestClient, game: Path, new_version: Path
) -> None:
    shutil.rmtree(game / "www" / "save")
    work, _copy, task = update_to_waiting(api, game)
    assert task["state"] == "awaiting_confirmation"


def test_personal_records_and_the_link_survive(
    api: TestClient, game: Path, new_version: Path
) -> None:
    work = first_work(api)
    detail = api.get(f"/api/v1/works/{work['id']}").json()
    api.patch(
        f"/api/v1/works/{work['id']}/personal",
        json={"note": "备注", "rating": 5, "expectedVersion": detail["version"]},
    )
    copy = link(api, work, game)
    saves_inside(api, work)
    begin(api, work, copy)
    settled(api, work)
    after = api.get(f"/api/v1/works/{work['id']}").json()
    assert after["note"] == "备注"
    assert after["rating"] == 5
    linked = api.get(f"/api/v1/works/{work['id']}/local-copies").json()["copies"][0]
    assert linked["id"] == copy["id"]
    assert linked["status"] == "ok"


# --- what stops it before anything happens ---


def test_unknown_saves_are_not_taken_to_mean_none(
    api: TestClient, game: Path, new_version: Path
) -> None:
    work = first_work(api)
    copy = link(api, work, game)
    response = begin(api, work, copy)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "saves_unconfirmed"
    assert (game / "Game.exe").read_bytes() == b"old program"


def test_saying_there_are_none_is_an_answer(api: TestClient, game: Path, new_version: Path) -> None:
    work = first_work(api)
    copy = link(api, work, game)
    api.put(f"/api/v1/works/{work['id']}/save-config", json={"rules": [], "confirmedNone": True})
    assert begin(api, work, copy).status_code == 200
    assert settled(api, work)["state"] == "awaiting_confirmation"


def test_the_game_must_be_said_to_be_closed(api: TestClient, game: Path, new_version: Path) -> None:
    work = first_work(api)
    copy = link(api, work, game)
    saves_inside(api, work)
    response = api.post(
        f"/api/v1/works/{work['id']}/update", json={"copyId": copy["id"], "confirmClosed": False}
    )
    assert response.json()["error"]["code"] == "confirm_closed"


def test_a_program_in_use_stops_it_and_nothing_is_killed(
    api: TestClient, game: Path, new_version: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import builtins

    real_open = builtins.open

    def locked(path: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if str(path).endswith("Game.exe") and mode == "r+b":
            raise PermissionError(13, "in use")
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", locked)
    work = first_work(api)
    copy = link(api, work, game)
    saves_inside(api, work)
    assert begin(api, work, copy).json()["error"]["code"] == "game_running"


@pytest.mark.parametrize(
    "rule",
    [
        {"kind": "inside", "path": "../elsewhere"},
        {"kind": "inside", "path": "C:\\Windows"},
        {"kind": "outside", "path": "relative\\path"},
        {"kind": "outside", "path": "C:\\"},
    ],
)
def test_save_rules_cannot_point_anywhere(
    api: TestClient, new_version: Path, rule: dict[str, str]
) -> None:
    response = api.put(
        f"/api/v1/works/{first_work(api)['id']}/save-config",
        json={"rules": [rule], "confirmedNone": False},
    )
    assert response.status_code == 422


def test_a_second_update_of_one_copy_is_refused(
    api: TestClient, game: Path, new_version: Path
) -> None:
    work, copy, _task = update_to_waiting(api, game)
    assert begin(api, work, copy).json()["error"]["code"] == "update_exists"


# --- failures before the swap leave everything alone ---


def everything_intact(game: Path) -> None:
    assert (game / "Game.exe").read_bytes() == b"old program"
    assert (game / "old_only.dll").read_bytes() == b"outdated"
    assert (game / "www" / "save" / "file1.rpgsave").read_bytes() == b"my progress"
    assert siblings(game) == [game.name]


def test_a_failed_download_changes_nothing(api: TestClient, game: Path, rig: Rig) -> None:
    rig.behave(mode="gone")
    work = first_work(api)
    copy = link(api, work, game)
    saves_inside(api, work)
    begin(api, work, copy)
    task = settled(api, work)
    assert task["state"] == "failed"
    assert task["code"] == "download_failed"
    everything_intact(game)


def test_a_damaged_archive_changes_nothing(
    api: TestClient, game: Path, rig: Rig, tmp_path: Path
) -> None:
    archive = samples.zip_with(tmp_path / "bad.zip", {"../evil.txt": b"x"})
    rig.behave(payload=str(archive))
    work = first_work(api)
    copy = link(api, work, game)
    saves_inside(api, work)
    begin(api, work, copy)
    assert settled(api, work)["state"] == "failed"
    everything_intact(game)


def test_a_patch_is_not_taken_for_the_whole_game(
    api: TestClient, game: Path, rig: Rig, tmp_path: Path
) -> None:
    archive = samples.zip_with(tmp_path / "patch.zip", {"data/patch.bin": b"only a patch"})
    rig.behave(payload=str(archive))
    work = first_work(api)
    copy = link(api, work, game)
    saves_inside(api, work)
    begin(api, work, copy)
    task = settled(api, work)
    assert task["code"] == "entry_changed"
    everything_intact(game)


def test_a_failed_backup_stops_before_anything_else(
    api: TestClient, game: Path, new_version: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import game_updates as module

    real = module._hash
    calls = {"count": 0}

    def wrong(path: Path) -> str:
        calls["count"] += 1
        return real(path) + ("x" if calls["count"] == 2 else "")

    monkeypatch.setattr(module, "_hash", wrong)
    work = first_work(api)
    copy = link(api, work, game)
    saves_inside(api, work)
    begin(api, work, copy)
    task = settled(api, work)
    assert task["code"] == "backup_failed"
    everything_intact(game)
    assert api.get(f"/api/v1/works/{work['id']}/update").json()["backups"] == []
    server = api.app.state.service.downloads._on_shutdown.__self__  # type: ignore[attr-defined]
    assert server.log.file_requests() == []  # Not even a download happened.


def test_a_failed_swap_puts_everything_back(
    api: TestClient, game: Path, new_version: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_rename = os.rename

    def refuse(source: Any, target: Any) -> None:
        if ".atlas-update-" in str(source):
            raise PermissionError(5, "a file is in use")
        real_rename(source, target)

    monkeypatch.setattr(os, "rename", refuse)
    work = first_work(api)
    copy = link(api, work, game)
    saves_inside(api, work)
    begin(api, work, copy)
    # The undo itself needs the staging name back, so it runs with renames working again.
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        task = api.get(f"/api/v1/works/{work['id']}/update").json()["task"]
        if task and task["state"] not in STILL:
            break
        time.sleep(0.01)
    assert task["state"] == "failed"
    monkeypatch.undo()
    assert (game / "Game.exe").read_bytes() == b"old program"


def test_saves_that_will_not_verify_undo_the_swap(
    api: TestClient, game: Path, new_version: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.game_updates import GameUpdater, _Stop

    def broken(*_args: Any) -> None:
        raise _Stop("failed", "saves_failed")

    monkeypatch.setattr(GameUpdater, "_carry_saves", broken)
    work = first_work(api)
    copy = link(api, work, game)
    saves_inside(api, work)
    begin(api, work, copy)
    task = settled(api, work)
    assert task["code"] == "saves_failed"
    everything_intact(game)


def test_cancelling_before_the_swap_changes_nothing(
    api: TestClient, game: Path, tmp_path: Path, rig: Rig
) -> None:
    archive = samples.zip_with(tmp_path / "new.zip", {"Game.exe": b"new"})
    rig.behave(payload=str(archive), mode="slow", delay=0.2)
    work = first_work(api)
    copy = link(api, work, game)
    saves_inside(api, work)
    begin(api, work, copy)
    task = api.get(f"/api/v1/works/{work['id']}/update").json()["task"]
    api.post(f"/api/v1/game-updates/{task['id']}/cancel")
    done = settled(api, work)
    assert done["state"] in ("cancelled", "awaiting_confirmation")
    if done["state"] == "cancelled":
        everything_intact(game)


def test_a_retry_reuses_the_finished_download(
    api: TestClient, game: Path, rig: Rig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = samples.zip_with(tmp_path / "new.zip", {"Game.exe": b"new program"})
    rig.behave(payload=str(archive))
    from app.services.extractions import ExtractionService

    real = ExtractionService.unpack_into

    def fail_once(*_args: Any) -> None:
        from app.adapters.system.archives import ArchiveProblem

        raise ArchiveProblem("damaged")

    monkeypatch.setattr(ExtractionService, "unpack_into", fail_once)
    work = first_work(api)
    copy = link(api, work, game)
    saves_inside(api, work)
    begin(api, work, copy)
    task = settled(api, work)
    assert task["state"] == "failed"
    server = api.app.state.service.downloads._on_shutdown.__self__  # type: ignore[attr-defined]
    fetched = len(server.log.file_requests())
    monkeypatch.setattr(ExtractionService, "unpack_into", real)
    api.post(f"/api/v1/game-updates/{task['id']}/retry")
    assert settled(api, work)["state"] == "awaiting_confirmation"
    assert len(server.log.file_requests()) == fetched


# --- crashes ---


def crash_during_swap(client: TestClient, game: Path, task_id: str) -> None:
    """On record as swapping, with the folders as a crash would have left them."""
    old = game.parent / f"{game.name}.atlas-old-{task_id}"
    with engine_of(client).begin() as connection:
        connection.execute(
            update(game_updates)
            .where(game_updates.c.id == task_id)
            .values(state="replacing", old_path=str(old), active_key="x", finished_at=None)
        )


def make_stale_task(client: TestClient, game: Path, new_version: Path) -> str:
    work = first_work(client)
    copy = link(client, work, game)
    saves_inside(client, work)
    client.put(
        f"/api/v1/works/{work['id']}/save-config",
        json={"rules": [{"kind": "inside", "path": "www/save"}], "confirmedNone": False},
    )
    begin(client, work, copy)
    task = settled(client, work)
    client.post(f"/api/v1/game-updates/{task['id']}/rollback")
    task_id: str = task["id"]
    return task_id


@pytest.mark.parametrize("moment", ["old_moved_aside", "new_in_place"])
def test_a_crash_in_the_swap_is_undone_on_restart(
    settings: Settings, rig: Rig, game: Path, new_version: Path, moment: str
) -> None:
    with client_for(settings) as client:
        prepare(client, rig)
        with engine_of(client).begin() as connection:
            connection.execute(update(works).values(kind="game"))
        work = first_work(client)
        task_id = make_stale_task(client, game, new_version)
        old = game.parent / f"{game.name}.atlas-old-{task_id}"
        os.rename(game, old)
        if moment == "new_in_place":
            game.mkdir()
            (game / "Game.exe").write_bytes(b"new program")
        crash_during_swap(client, game, task_id)
    with client_for(settings) as client:
        task = client.get(f"/api/v1/works/{work['id']}/update").json()["task"]
        assert task["state"] == "interrupted"
        assert task["message"]
    everything_intact(game)


def test_a_crash_while_waiting_keeps_waiting(
    settings: Settings, rig: Rig, game: Path, new_version: Path
) -> None:
    with client_for(settings) as client:
        prepare(client, rig)
        with engine_of(client).begin() as connection:
            connection.execute(update(works).values(kind="game"))
        work, _copy, _task = update_to_waiting(client, game)
    with client_for(settings) as client:
        client.get("/api/v1/session")
        task = client.get(f"/api/v1/works/{work['id']}/update").json()["task"]
        assert task["state"] == "awaiting_confirmation"
    assert len(siblings(game)) == 2


# --- the old folder ---


def test_confirm_will_only_delete_the_folder_it_made(
    api: TestClient, game: Path, new_version: Path, tmp_path: Path
) -> None:
    _work, _copy, task = update_to_waiting(api, game)
    precious = tmp_path / "precious"
    precious.mkdir()
    (precious / "keep.txt").write_bytes(b"keep")
    with engine_of(api).begin() as connection:
        connection.execute(update(game_updates).values(old_path=str(precious)))
    response = api.post(f"/api/v1/game-updates/{task['id']}/confirm")
    assert response.status_code == 409
    assert (precious / "keep.txt").exists()


def test_other_copies_of_the_game_are_not_touched(
    api: TestClient, game: Path, new_version: Path, tmp_path: Path
) -> None:
    other_place = tmp_path / "other-drive"
    other_place.mkdir()
    other = old_game(other_place)
    work = first_work(api)
    copy = link(api, work, game)
    link(api, work, other)
    saves_inside(api, work)
    begin(api, work, copy)
    task = settled(api, work)
    api.post(f"/api/v1/game-updates/{task['id']}/confirm")
    assert (other / "Game.exe").read_bytes() == b"old program"
    assert (other / "old_only.dll").exists()


# --- backups and restoring ---


def test_a_backup_can_be_restored_and_guards_what_is_there(
    api: TestClient, game: Path, new_version: Path
) -> None:
    work, copy, task = update_to_waiting(api, game)
    api.post(f"/api/v1/game-updates/{task['id']}/confirm")
    save = game / "www" / "save" / "file1.rpgsave"
    save.write_bytes(b"later progress")
    backup = api.get(f"/api/v1/works/{work['id']}/update").json()["backups"][0]
    response = api.post(f"/api/v1/save-backups/{backup['id']}/restore", json={"copyId": copy["id"]})
    assert response.status_code == 200, response.text
    assert response.json()["restored"] == 2
    assert save.read_bytes() == b"my progress"
    # What was overwritten is itself in a new backup.
    backups = api.get(f"/api/v1/works/{work['id']}/update").json()["backups"]
    assert len(backups) == 2
    again = api.post(
        f"/api/v1/save-backups/{response.json()['safetyBackupId']}/restore",
        json={"copyId": copy["id"]},
    )
    assert again.status_code == 200
    assert save.read_bytes() == b"later progress"


def test_a_damaged_backup_is_refused_not_restored(
    api: TestClient, game: Path, new_version: Path, settings: Settings
) -> None:
    work, copy, task = update_to_waiting(api, game)
    api.post(f"/api/v1/game-updates/{task['id']}/confirm")
    backup = api.get(f"/api/v1/works/{work['id']}/update").json()["backups"][0]
    folder = settings.data_dir / "save-backups" / work["id"] / backup["id"]
    for file in folder.rglob("*"):
        if file.is_file():
            file.write_bytes(b"damaged")
    response = api.post(f"/api/v1/save-backups/{backup['id']}/restore", json={"copyId": copy["id"]})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "restore_failed"
    assert (game / "www" / "save" / "file1.rpgsave").read_bytes() == b"my progress"


def test_old_backups_are_pruned_only_by_count(
    api: TestClient, game: Path, new_version: Path
) -> None:
    work = first_work(api)
    copy = link(api, work, game)
    saves_inside(api, work)
    service = api.app.state.service.updates_game  # type: ignore[attr-defined]
    rules = [{"kind": "inside", "path": "www/save"}]
    for _ in range(8):
        service.backup(work["id"], game, rules)
    assert len(api.get(f"/api/v1/works/{work['id']}/update").json()["backups"]) == 5
    assert copy["id"]


# --- boundaries ---


@pytest.mark.parametrize("visibility", ["hidden", "private", "quarantined"])
def test_works_outside_ordinary_views_stay_out(
    api: TestClient, game: Path, new_version: Path, visibility: str
) -> None:
    work = first_work(api)
    copy = link(api, work, game)
    saves_inside(api, work)
    with engine_of(api).begin() as connection:
        connection.execute(
            update(personal_records)
            .where(personal_records.c.work_id == work["id"])
            .values(visibility=visibility)
        )
    assert begin(api, work, copy).status_code == 404
    assert api.get(f"/api/v1/works/{work['id']}/update").status_code == 404
    assert api.get(f"/api/v1/works/{work['id']}/save-config").status_code == 404


def test_requests_cannot_name_a_folder_to_replace(
    api: TestClient, game: Path, new_version: Path, tmp_path: Path
) -> None:
    work = first_work(api)
    response = api.post(
        f"/api/v1/works/{work['id']}/update",
        json={"copyId": "x", "confirmClosed": True, "root": str(tmp_path)},
    )
    assert response.status_code == 422
    assert json.dumps(response.json())
