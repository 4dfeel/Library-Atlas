"""Local copies through the real API and database. Launch tests run a copy of cmd.exe from a made-up
game folder, so a real process really starts and reports where it ran. No real game is involved."""

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
from app.db.schema import personal_records, works
from app.domain.local_files import EntryCandidate, entry_candidates, single_entry
from tests.conftest import client_for
from tests.test_downloads import Rig, engine_of, first_work, prepare, work_ids

BASE = "/api/v1/local-copies"
CMD = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe"


def game_folder(root: Path, name: str = "ゲーム フォルダ", program: str = "Game.exe") -> Path:
    folder = root / name
    (folder / "data").mkdir(parents=True)
    shutil.copyfile(CMD, folder / program)
    (folder / "data" / "セーブ.dat").write_bytes(b"save")
    return folder


def snapshot(folder: Path) -> dict[str, bytes]:
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in folder.rglob("*")
        if path.is_file()
    }


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


def add(client: TestClient, work_id: str, folder: Path, **body: Any) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/works/{work_id}/local-copies", json={"root": str(folder), **body}
    )
    assert response.status_code == 200, response.text
    copies: list[dict[str, Any]] = response.json()["copies"]
    return copies[0]


# --- which program ---


def names(*items: tuple[str, bool, int]) -> list[EntryCandidate]:
    return [EntryCandidate(*item) for item in items]


def test_helpers_are_told_apart_by_name(tmp_path: Path) -> None:
    for name in ("Game.exe", "unins000.exe", "setup.exe", "UnityCrashHandler64.exe", "Config.exe"):
        (tmp_path / name).write_bytes(b"x")
    found = {item.path: item.helper for item in entry_candidates(tmp_path)}
    assert found == {
        "Game.exe": False,
        "unins000.exe": True,
        "setup.exe": True,
        "UnityCrashHandler64.exe": True,
        "Config.exe": True,
    }


def test_one_plausible_program_is_suggested() -> None:
    assert single_entry(names(("Game.exe", False, 0), ("setup.exe", True, 0))) == "Game.exe"
    # A shallower one is the game; the deeper one is usually its tool.
    assert single_entry(names(("Game.exe", False, 0), ("tools/x.exe", False, 1))) == "Game.exe"


@pytest.mark.parametrize(
    "items",
    [
        (("a.exe", False, 0), ("b.exe", False, 0)),
        (("setup.exe", True, 0),),
        (),
    ],
)
def test_otherwise_no_program_is_chosen(items: tuple[tuple[str, bool, int], ...]) -> None:
    assert single_entry(names(*items)) is None


def test_looking_at_a_folder_is_bounded_and_keeps_inside(tmp_path: Path) -> None:
    deep = tmp_path / "a" / "b" / "c" / "d" / "e"
    deep.mkdir(parents=True)
    (deep / "too_deep.exe").write_bytes(b"x")
    (tmp_path / "redist").mkdir()
    (tmp_path / "redist" / "other.exe").write_bytes(b"x")
    assert entry_candidates(tmp_path) == []


def test_a_link_is_not_followed(tmp_path: Path) -> None:
    winapi = pytest.importorskip("_winapi")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "elsewhere.exe").write_bytes(b"x")
    folder = tmp_path / "game"
    folder.mkdir()
    winapi.CreateJunction(str(outside), str(folder / "link"))
    assert entry_candidates(folder) == []


# --- saving ---


def test_saving_runs_nothing_and_changes_nothing(api: TestClient, tmp_path: Path) -> None:
    folder = game_folder(tmp_path)
    before = snapshot(folder)
    work = first_work(api)
    preview = api.post(
        f"/api/v1/works/{work['id']}/local-copies/preview", json={"path": str(folder)}
    ).json()
    assert preview["suggested"] == "Game.exe"
    copy = add(api, work["id"], folder, entry="Game.exe")
    assert copy["status"] == "ok"
    assert copy["isDefault"] is True
    assert copy["origin"] == "manual"
    time.sleep(0.2)
    assert snapshot(folder) == before


def test_several_copies_with_a_clear_default(api: TestClient, tmp_path: Path) -> None:
    one = game_folder(tmp_path, "one")
    two = game_folder(tmp_path, "two")
    work = first_work(api)
    first = add(api, work["id"], one, entry="Game.exe")
    response = api.post(
        f"/api/v1/works/{work['id']}/local-copies", json={"root": str(two), "entry": "Game.exe"}
    ).json()["copies"]
    assert [copy["id"] for copy in response if copy["isDefault"]] == [first["id"]]
    other = next(copy for copy in response if copy["id"] != first["id"])
    after = api.post(f"{BASE}/{other['id']}/default").json()["copies"]
    assert [copy["id"] for copy in after if copy["isDefault"]] == [other["id"]]


def test_saving_the_same_folder_twice_is_one_copy(api: TestClient, tmp_path: Path) -> None:
    folder = game_folder(tmp_path)
    work = first_work(api)
    add(api, work["id"], folder)
    add(api, work["id"], Path(str(folder).upper()))
    assert len(api.get(f"/api/v1/works/{work['id']}/local-copies").json()["copies"]) == 1


def test_removing_a_copy_leaves_the_folder_alone(api: TestClient, tmp_path: Path) -> None:
    one = game_folder(tmp_path, "one")
    two = game_folder(tmp_path, "two")
    before = snapshot(one)
    work = first_work(api)
    first = add(api, work["id"], one, entry="Game.exe")
    add(api, work["id"], two)
    left = api.delete(f"{BASE}/{first['id']}").json()["copies"]
    assert snapshot(one) == before
    assert len(left) == 1
    assert left[0]["isDefault"] is True  # The other one takes over.


@pytest.mark.parametrize(
    "body",
    [
        {"entry": "..\\..\\Windows\\notepad.exe"},
        {"entry": "C:\\Windows\\notepad.exe"},
        {"entry": "data/セーブ.dat"},
        {"entry": "missing.exe"},
        {"working": "..\\.."},
        {"working": "nowhere"},
        {"arguments": ["x"] * 21},
        {"arguments": ["x" * 501]},
    ],
)
def test_bad_choices_are_refused(api: TestClient, tmp_path: Path, body: dict[str, Any]) -> None:
    folder = game_folder(tmp_path)
    response = api.post(
        f"/api/v1/works/{first_work(api)['id']}/local-copies", json={"root": str(folder), **body}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "copy_invalid"


@pytest.mark.parametrize("which", ["script", "shortcut"])
def test_only_a_program_can_be_the_entry(api: TestClient, tmp_path: Path, which: str) -> None:
    folder = game_folder(tmp_path)
    name = "run.bat" if which == "script" else "game.lnk"
    (folder / name).write_bytes(b"x")
    response = api.post(
        f"/api/v1/works/{first_work(api)['id']}/local-copies",
        json={"root": str(folder), "entry": name},
    )
    assert response.status_code == 422


def test_system_and_atlas_folders_cannot_be_linked(api: TestClient, settings: Settings) -> None:
    work = first_work(api)
    for path in (os.environ["SystemRoot"], str(settings.data_dir), "relative\\path", "Z:\\nope"):
        response = api.post(f"/api/v1/works/{work['id']}/local-copies", json={"root": path})
        assert response.status_code == 422, path


def test_a_link_inside_cannot_lead_out(api: TestClient, tmp_path: Path) -> None:
    winapi = pytest.importorskip("_winapi")
    outside = tmp_path / "outside"
    outside.mkdir()
    shutil.copyfile(CMD, outside / "x.exe")
    folder = game_folder(tmp_path)
    winapi.CreateJunction(str(outside), str(folder / "link"))
    response = api.post(
        f"/api/v1/works/{first_work(api)['id']}/local-copies",
        json={"root": str(folder), "entry": "link/x.exe"},
    )
    assert response.status_code == 422


def test_the_folder_chooser_is_only_a_chooser(api: TestClient, rig: Rig, tmp_path: Path) -> None:
    rig.control["pick"] = str(tmp_path)
    rig.save_control()
    assert api.post(f"{BASE}/choose-folder").json()["path"] == str(tmp_path)


# --- starting ---


def launch_and_wait(client: TestClient, copy_id: str, output: Path) -> None:
    response = client.post(f"{BASE}/{copy_id}/launch")
    assert response.status_code == 200, response.text
    assert response.json()["submitted"] is True
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if output.exists() and output.read_bytes():
            return
        time.sleep(0.05)
    raise AssertionError("the program did not run")


def test_a_click_really_starts_it_with_the_right_folder_and_arguments(
    api: TestClient, tmp_path: Path
) -> None:
    folder = game_folder(tmp_path)
    copy = add(
        api,
        first_work(api)["id"],
        folder,
        entry="Game.exe",
        working="data",
        arguments=["/c", "cd", ">", "where i ran.txt"],
    )
    launch_and_wait(api, copy["id"], folder / "data" / "where i ran.txt")
    written = (folder / "data" / "where i ran.txt").read_bytes()
    assert b"data" in written


def test_the_working_folder_defaults_to_the_programs_own(api: TestClient, tmp_path: Path) -> None:
    folder = game_folder(tmp_path)
    copy = add(
        api, first_work(api)["id"], folder, entry="Game.exe", arguments=["/c", "cd", ">", "o.txt"]
    )
    launch_and_wait(api, copy["id"], folder / "o.txt")


def test_arguments_are_never_a_shell_command(api: TestClient, tmp_path: Path) -> None:
    """Run through a program that is not a shell: `&` stays an ordinary argument."""
    folder = game_folder(tmp_path)
    shutil.copyfile(Path(os.environ["SystemRoot"]) / "System32" / "where.exe", folder / "Tool.exe")
    canary = tmp_path / "canary.txt"
    copy = add(
        api,
        first_work(api)["id"],
        folder,
        entry="Tool.exe",
        arguments=["x", "&", "cmd", "/c", f"echo hit > {canary}"],
    )
    assert api.post(f"{BASE}/{copy['id']}/launch").json()["submitted"] is True
    time.sleep(1)
    assert not canary.exists()


def test_a_quick_second_click_does_not_start_it_twice(api: TestClient, tmp_path: Path) -> None:
    folder = game_folder(tmp_path)
    copy = add(api, first_work(api)["id"], folder, entry="Game.exe", arguments=["/c", "echo", "x"])
    first = api.post(f"{BASE}/{copy['id']}/launch").json()
    second = api.post(f"{BASE}/{copy['id']}/launch").json()
    assert first == {"submitted": True, "repeated": False}
    assert second == {"submitted": False, "repeated": True}


def test_it_can_be_started_again_later(api: TestClient, tmp_path: Path) -> None:
    folder = game_folder(tmp_path)
    copy = add(api, first_work(api)["id"], folder, entry="Game.exe", arguments=["/c", "echo", "x"])
    service = api.app.state.service.local_copies  # type: ignore[attr-defined]
    now = [100.0]
    service._clock = lambda: now[0]
    assert api.post(f"{BASE}/{copy['id']}/launch").json()["submitted"] is True
    now[0] += 5
    assert api.post(f"{BASE}/{copy['id']}/launch").json()["submitted"] is True


@pytest.mark.parametrize(
    ("change", "code"),
    [("delete_entry", "copy_entry_missing"), ("delete_root", "copy_root_missing")],
)
def test_a_changed_folder_is_reported_when_used(
    api: TestClient, tmp_path: Path, change: str, code: str
) -> None:
    folder = game_folder(tmp_path)
    copy = add(api, first_work(api)["id"], folder, entry="Game.exe")
    if change == "delete_entry":
        (folder / "Game.exe").unlink()
    else:
        shutil.rmtree(folder)
    response = api.post(f"{BASE}/{copy['id']}/launch")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == code
    listed = api.get(f"/api/v1/works/{copy['workId']}/local-copies").json()["copies"]
    assert listed[0]["message"]  # The record stays, and says what is wrong.


def test_an_offline_drive_is_not_a_deleted_work(api: TestClient, tmp_path: Path) -> None:
    folder = game_folder(tmp_path)
    work = first_work(api)
    copy = add(api, work["id"], folder, entry="Game.exe")
    from app.db.schema import local_copies

    with engine_of(api).begin() as connection:
        connection.execute(update(local_copies).values(root_path="Z:\\未连接的硬盘\\ゲーム"))
    listed = api.get(f"/api/v1/works/{work['id']}/local-copies").json()["copies"]
    assert [item["id"] for item in listed] == [copy["id"]]
    assert listed[0]["status"] == "offline"
    assert api.get(f"/api/v1/works/{work['id']}").status_code == 200


def test_a_program_that_cannot_start_says_so(api: TestClient, tmp_path: Path) -> None:
    folder = game_folder(tmp_path)
    (folder / "Broken.exe").write_bytes(b"this is not a program")
    copy = add(api, first_work(api)["id"], folder, entry="Broken.exe")
    response = api.post(f"{BASE}/{copy['id']}/launch")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "launch_failed"


def test_relocating_keeps_the_copy(api: TestClient, tmp_path: Path) -> None:
    folder = game_folder(tmp_path, "old")
    work = first_work(api)
    copy = add(api, work["id"], folder, entry="Game.exe")
    moved = tmp_path / "new"
    folder.rename(moved)
    assert api.get(f"/api/v1/works/{work['id']}/local-copies").json()["copies"][0]["status"] == (
        "root_missing"
    )
    response = api.patch(f"{BASE}/{copy['id']}", json={"root": str(moved)})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["id"] == copy["id"]


def test_only_games_start(api: TestClient, tmp_path: Path) -> None:
    folder = game_folder(tmp_path)
    work = first_work(api)
    copy = add(api, work["id"], folder, entry="Game.exe")
    with engine_of(api).begin() as connection:
        connection.execute(update(works).where(works.c.id == work["id"]).values(kind="audio"))
    assert api.post(f"{BASE}/{copy['id']}/launch").json()["error"]["code"] == "launch_unsupported"
    assert api.post(f"{BASE}/{copy['id']}/open").status_code == 200


def test_a_request_cannot_name_something_to_run(api: TestClient, tmp_path: Path) -> None:
    folder = game_folder(tmp_path)
    copy = add(api, first_work(api)["id"], folder, entry="Game.exe")
    response = api.post(f"{BASE}/{copy['id']}/launch", json={"command": "calc.exe"})
    assert response.json().get("submitted") is True or response.status_code == 422
    assert api.post(f"{BASE}/C:%5CWindows%5Cnotepad.exe/launch").status_code in (404, 405)


@pytest.mark.parametrize("visibility", ["hidden", "private", "quarantined"])
def test_works_outside_ordinary_views_stay_out(
    api: TestClient, tmp_path: Path, visibility: str
) -> None:
    folder = game_folder(tmp_path)
    work = first_work(api)
    copy = add(api, work["id"], folder, entry="Game.exe")
    with engine_of(api).begin() as connection:
        connection.execute(
            update(personal_records)
            .where(personal_records.c.work_id == work["id"])
            .values(visibility=visibility)
        )
    assert api.get(f"/api/v1/works/{work['id']}/local-copies").status_code == 404
    assert api.post(f"{BASE}/{copy['id']}/launch").status_code == 404
    assert api.post(f"{BASE}/{copy['id']}/open").status_code == 404


def test_copies_survive_a_restart(settings: Settings, rig: Rig, tmp_path: Path) -> None:
    folder = game_folder(tmp_path)
    with client_for(settings) as client:
        prepare(client, rig)
        work = first_work(client)
        add(client, work["id"], folder)
    with client_for(settings) as client:
        copies = client.get(f"/api/v1/works/{work['id']}/local-copies").json()["copies"]
        assert copies[0]["root"] == str(folder)


def test_unpacking_records_a_copy_and_a_second_work_stays_apart(
    api: TestClient, rig: Rig, tmp_path: Path
) -> None:
    from tests import archive_samples as samples
    from tests.test_downloads import ended, start

    archive = samples.zip_with(tmp_path / "a.zip", {"Game.exe": b"x", "data/a.txt": b"y"})
    rig.behave(payload=str(archive))
    one, two = work_ids(api)[:2]
    for task in start(api, one["id"], extract=True):
        ended(api, task["id"])
    deadline = time.monotonic() + 15
    copies: list[dict[str, Any]] = []
    while time.monotonic() < deadline and not copies:
        copies = api.get(f"/api/v1/works/{one['id']}/local-copies").json()["copies"]
        time.sleep(0.05)
    assert copies[0]["origin"] == "unpacked"
    assert copies[0]["entry"] == "Game.exe"  # The one plausible program, and it was not run.
    assert api.get(f"/api/v1/works/{two['id']}/local-copies").json()["copies"] == []
