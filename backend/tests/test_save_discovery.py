"""Finding saves, against made-up games and a made-up user folder. No test reads the real AppData or
real registry except the one that writes and removes its own throwaway key."""

import json
import os
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.adapters.system.registry import (
    FileRegistry,
    RegistryRefused,
    WindowsRegistry,
    player_values,
    subkey_of,
)
from app.core.config import Settings
from app.db.schema import personal_records
from app.domain.save_hints import KnownFolders, read_facts
from tests.conftest import client_for, write_headers
from tests.test_downloads import Rig, engine_of, prepare, work_ids


def home_of(settings: Settings) -> Path:
    return settings.data_dir / "fake-home"


def folders_at(home: Path) -> KnownFolders:
    return KnownFolders(
        home / "AppData" / "Local",
        home / "AppData" / "LocalLow",
        home / "AppData" / "Roaming",
        home / "Documents",
        home / "Saved Games",
    )


def make_game(parent: Path, name: str = "synthetic game") -> Path:
    folder = parent / name
    folder.mkdir(parents=True)
    (folder / "Game.exe").write_bytes(b"program")
    return folder


def wait_done(client: TestClient, work_id: str) -> dict[str, Any]:
    for _attempt in range(400):
        data: dict[str, Any] = client.get(f"/api/v1/works/{work_id}/saves/suggestions").json()
        if data["session"]["state"] in ("done", "failed"):
            return data
        time.sleep(0.02)
    raise AssertionError("scan did not finish")


@pytest.fixture
def rig(settings: Settings, tmp_path: Path) -> Rig:
    return Rig(settings, tmp_path)


@pytest.fixture
def api(settings: Settings, rig: Rig) -> Iterator[TestClient]:
    with client_for(settings) as client:
        prepare(client, rig)
        yield client


def link(client: TestClient, work_id: str, folder: Path) -> None:
    response = client.post(
        f"/api/v1/works/{work_id}/local-copies", json={"root": str(folder), "entry": "Game.exe"}
    )
    assert response.status_code == 200, response.text


def suggest(client: TestClient, work_id: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/works/{work_id}/saves/suggestions")
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def by_path(data: dict[str, Any], fragment: str) -> dict[str, Any]:
    found: dict[str, Any] = next(i for i in data["suggestions"] if fragment in i["path"])
    return found


# --- reading a game's own files ---


def test_unity_is_read_from_its_own_app_info(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    (game / "Game_Data").mkdir()
    (game / "Game_Data" / "app.info").write_text("合成社团\n合成游戏\n", encoding="utf-8")
    facts = read_facts(game, folders_at(tmp_path / "home"))
    assert facts.engine == "Unity"
    assert facts.company == "合成社团"
    kinds = {hint.kind: hint.path for hint in facts.hints}
    assert kinds["outside"].endswith(str(Path("LocalLow") / "合成社团" / "合成游戏"))
    assert kinds["registry"] == "HKCU\\Software\\合成社团\\合成游戏"


@pytest.mark.parametrize(
    "content",
    ["..\\..\nevil\n", "good\n..\\..\\Windows\n", "a/b\nc\n", "C:\\x\ny\n", "only one line\n"],
)
def test_a_games_app_info_cannot_steer_a_path(tmp_path: Path, content: str) -> None:
    game = make_game(tmp_path)
    (game / "Game_Data").mkdir()
    (game / "Game_Data" / "app.info").write_text(content, encoding="utf-8")
    facts = read_facts(game, folders_at(tmp_path / "home"))
    assert facts.engine == "Unity"
    assert not [hint for hint in facts.hints if hint.kind in ("outside", "registry")]


@pytest.mark.parametrize(
    ("marker", "engine", "folder"),
    [
        ("www/js/rpg_core.js", "RPG Maker MV", "www/save"),
        ("js/rmmz_core.js", "RPG Maker MZ", "save"),
        ("data.xp3", "KiriKiri", "savedata"),
        ("Data.wolf", "Wolf RPG", "Save"),
    ],
)
def test_common_engines_and_their_folders(
    tmp_path: Path, marker: str, engine: str, folder: str
) -> None:
    game = make_game(tmp_path)
    (game / marker).parent.mkdir(parents=True, exist_ok=True)
    (game / marker).write_bytes(b"x")
    (game / folder).mkdir(parents=True)
    facts = read_facts(game, folders_at(tmp_path / "home"))
    assert facts.engine == engine
    assert [hint.path for hint in facts.hints] == [folder]


def test_rpg_maker_save_files_at_the_top_become_a_pattern(tmp_path: Path) -> None:
    game = make_game(tmp_path)
    (game / "Game.rgss3a").write_bytes(b"x")
    (game / "Save01.rvdata2").write_bytes(b"x")
    facts = read_facts(game, folders_at(tmp_path / "home"))
    assert [hint.path for hint in facts.hints] == ["Save*.rvdata2"]


def test_links_are_not_followed_when_reading(tmp_path: Path) -> None:
    winapi = pytest.importorskip("_winapi")
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "save").mkdir(parents=True)
    game = make_game(tmp_path)
    winapi.CreateJunction(str(elsewhere / "save"), str(game / "save"))
    assert read_facts(game, folders_at(tmp_path / "home")).hints == ()


# --- engine suggestions through the API ---


def test_only_what_is_really_there_is_suggested(
    api: TestClient, settings: Settings, tmp_path: Path
) -> None:
    work = work_ids(api)[0]
    game = make_game(tmp_path)
    (game / "Game_Data").mkdir()
    (game / "Game_Data" / "app.info").write_text("Synth\nGame\n", encoding="utf-8")
    link(api, work["id"], game)
    data = suggest(api, work["id"])
    assert data["engine"] == "Unity"
    assert data["suggestions"] == []
    place = folders_at(home_of(settings)).local_low / "Synth" / "Game"
    place.mkdir(parents=True)
    (place / "slot.dat").write_bytes(b"12345")
    item = suggest(api, work["id"])["suggestions"][0]
    assert item["kind"] == "outside"
    assert item["files"] == 1
    assert item["sizeBytes"] == 5
    assert item["samples"] == ["slot.dat"]
    assert item["likely"] is True
    assert item["configured"] is False


def test_nothing_is_decided_for_the_user(
    api: TestClient, settings: Settings, tmp_path: Path
) -> None:
    work = work_ids(api)[0]
    game = make_game(tmp_path)
    (game / "save").mkdir()
    (game / "save" / "a.dat").write_bytes(b"x")
    link(api, work["id"], game)
    assert suggest(api, work["id"])["suggestions"]
    assert api.get(f"/api/v1/works/{work['id']}/save-config").json()["rules"] == []


# --- a session of play ---


def play(client: TestClient, work_id: str, write: Any) -> dict[str, Any]:
    assert client.post(f"/api/v1/works/{work_id}/saves/session").status_code == 200
    write()
    assert client.post(f"/api/v1/works/{work_id}/saves/session/finish").status_code == 200
    return wait_done(client, work_id)


def old(path: Path) -> None:
    """As if written long before this session."""
    stamp = time.time() - 86400
    os.utime(path, (stamp, stamp))


def test_a_session_finds_what_changed_in_appdata_and_names_the_programs_folder(
    api: TestClient, settings: Settings, tmp_path: Path
) -> None:
    work = work_ids(api)[0]
    game = make_game(tmp_path, "合成の冒険")
    link(api, work["id"], game)
    place = folders_at(home_of(settings)).roaming / "合成の冒険" / "profiles" / "main"

    def write() -> None:
        place.mkdir(parents=True)
        (place / "slot1.sav").write_bytes(b"data")

    data = play(api, work["id"], write)
    item = by_path(data, "合成の冒険")
    assert item["source"] == "play"
    assert item["likely"] is True
    assert item["path"].endswith(str(Path("Roaming") / "合成の冒険" / "profiles"))
    assert "名字" in item["reason"]
    assert item["files"] == 1


def test_a_session_ignores_what_did_not_change_and_the_usual_noise(
    api: TestClient, settings: Settings, tmp_path: Path
) -> None:
    work = work_ids(api)[0]
    game = make_game(tmp_path)
    link(api, work["id"], game)
    known = folders_at(home_of(settings))
    stale = known.roaming / "OldProgram"
    stale.mkdir(parents=True)
    (stale / "old.sav").write_bytes(b"x")
    old(stale / "old.sav")
    noisy = {
        known.local / "Google" / "Chrome" / "User Data" / "Default" / "History": b"x",
        known.local / "Temp" / "something.dat": b"x",
        known.local / "SomeApp" / "Cache" / "blob": b"x",
        known.local_low / "Synth" / "Game" / "Player.log": b"x",
        known.roaming / "Discord" / "settings.json": b"x",
    }

    def write() -> None:
        for path, content in noisy.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        (game / "new.log").write_bytes(b"x")

    data = play(api, work["id"], write)
    assert data["suggestions"] == []


def test_another_programs_folder_is_shown_only_as_unlikely(
    api: TestClient, settings: Settings, tmp_path: Path
) -> None:
    work = work_ids(api)[0]
    game = make_game(tmp_path)
    link(api, work["id"], game)
    other = folders_at(home_of(settings)).local / "SomeNotesApp" / "state"

    def write() -> None:
        other.mkdir(parents=True)
        (other / "window.json").write_bytes(b"x")

    data = play(api, work["id"], write)
    assert by_path(data, "SomeNotesApp")["likely"] is False


def test_files_written_inside_the_game_are_found_and_a_slot_becomes_a_pattern(
    api: TestClient, tmp_path: Path
) -> None:
    work = work_ids(api)[0]
    game = make_game(tmp_path)
    link(api, work["id"], game)

    def write() -> None:
        (game / "Save03.rvdata2").write_bytes(b"x")
        (game / "userfolder").mkdir()
        (game / "userfolder" / "state.bin").write_bytes(b"x")

    data = play(api, work["id"], write)
    assert by_path(data, "Save*.rvdata2")["kind"] == "inside"
    assert by_path(data, "Save*.rvdata2")["likely"] is True
    assert by_path(data, "userfolder")["kind"] == "inside"


def test_settings_alone_rank_below_a_save(
    api: TestClient, settings: Settings, tmp_path: Path
) -> None:
    work = work_ids(api)[0]
    game = make_game(tmp_path)
    link(api, work["id"], game)

    def write() -> None:
        (game / "config.ini").write_bytes(b"x")
        (game / "save").mkdir()
        (game / "save" / "slot1.dat").write_bytes(b"x")

    data = play(api, work["id"], write)
    paths = [item["path"] for item in data["suggestions"]]
    assert paths[0] == "save"
    assert by_path(data, "config.ini")["likely"] is False


def test_unity_player_prefs_that_changed_are_suggested(
    api: TestClient, settings: Settings, tmp_path: Path
) -> None:
    work = work_ids(api)[0]
    game = make_game(tmp_path)
    (game / "Game_Data").mkdir()
    (game / "Game_Data" / "app.info").write_text("Synth\nGame\n", encoding="utf-8")
    link(api, work["id"], game)
    registry = FileRegistry(settings.data_dir / "fake-registry.json")

    def write() -> None:
        registry.write(
            "HKCU\\Software\\Synth\\Game",
            {"values": {"progress_h1": {"type": 4, "data": 7}}, "keys": {}},
        )

    data = play(api, work["id"], write)
    item = by_path(data, "HKCU")
    assert item["kind"] == "registry"
    assert item["likely"] is True
    assert item["files"] == 1


def test_a_key_with_only_window_settings_is_no_save(
    api: TestClient, settings: Settings, tmp_path: Path
) -> None:
    work = work_ids(api)[0]
    game = make_game(tmp_path)
    (game / "Game_Data").mkdir()
    (game / "Game_Data" / "app.info").write_text("Synth\nGame\n", encoding="utf-8")
    link(api, work["id"], game)
    registry = FileRegistry(settings.data_dir / "fake-registry.json")

    def write() -> None:
        registry.write(
            "HKCU\\Software\\Synth\\Game",
            {
                "values": {"Screenmanager Resolution Width_h1": {"type": 4, "data": 1920}},
                "keys": {},
            },
        )

    data = play(api, work["id"], write)
    assert not [item for item in data["suggestions"] if item["kind"] == "registry"]


def test_a_launch_records_only_when_the_saves_are_not_settled(
    api: TestClient, settings: Settings, tmp_path: Path
) -> None:
    work = work_ids(api)[0]
    game = make_game(tmp_path)
    link(api, work["id"], game)
    service = api.app.state.service.discovery  # type: ignore[attr-defined]
    api.put(
        f"/api/v1/works/{work['id']}/save-config",
        json={"rules": [{"kind": "inside", "path": "save"}], "confirmedNone": False},
    )
    service.game_started(work["id"])
    assert suggest(api, work["id"])["session"]["state"] == "none"
    api.put(f"/api/v1/works/{work['id']}/save-config", json={"rules": [], "confirmedNone": False})
    service.game_started(work["id"])
    assert suggest(api, work["id"])["session"]["state"] == "recording"


def test_the_scan_runs_by_itself_once_the_game_has_ended(
    api: TestClient, settings: Settings, tmp_path: Path
) -> None:
    work = work_ids(api)[0]
    game = make_game(tmp_path)
    link(api, work["id"], game)
    service = api.app.state.service.discovery  # type: ignore[attr-defined]
    service.after_exit_seconds = 0.0
    service.game_started(work["id"])
    (game / "save").mkdir()
    (game / "save" / "a.sav").write_bytes(b"x")
    service.game_exited(work["id"], game / "Game.exe")
    data = wait_done(api, work["id"])
    assert by_path(data, "save")["likely"] is True


def test_a_game_started_elsewhere_waits_for_the_user(
    api: TestClient, settings: Settings, tmp_path: Path
) -> None:
    work = work_ids(api)[0]
    game = make_game(tmp_path)
    link(api, work["id"], game)
    api.post(f"/api/v1/works/{work['id']}/saves/session")
    assert suggest(api, work["id"])["session"]["state"] == "recording"


def test_a_session_outlives_a_restart(settings: Settings, rig: Rig, tmp_path: Path) -> None:
    with client_for(settings) as client:
        prepare(client, rig)
        work = work_ids(client)[0]
        game = make_game(tmp_path)
        link(client, work["id"], game)
        client.post(f"/api/v1/works/{work['id']}/saves/session")
    (game / "save").mkdir()
    (game / "save" / "a.sav").write_bytes(b"x")
    with client_for(settings) as client:
        client.headers.update(write_headers(client))
        assert suggest(client, work["id"])["session"]["state"] == "recording"
        client.post(f"/api/v1/works/{work['id']}/saves/session/finish")
        assert by_path(wait_done(client, work["id"]), "save")["likely"] is True


def test_it_stops_at_its_budget_and_says_so(
    api: TestClient, settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import save_discovery

    work = work_ids(api)[0]
    game = make_game(tmp_path)
    link(api, work["id"], game)
    monkeypatch.setattr(save_discovery, "MAX_ENTRIES", 1)
    place = folders_at(home_of(settings)).roaming / "Many"
    place.mkdir(parents=True)

    def write() -> None:
        for index in range(5):
            (place / f"{index}.sav").write_bytes(b"x")

    assert play(api, work["id"], write)["session"]["complete"] is False


@pytest.mark.parametrize("visibility", ["hidden", "private", "quarantined"])
def test_works_outside_ordinary_views_are_silent(
    api: TestClient, tmp_path: Path, visibility: str
) -> None:
    work = work_ids(api)[0]
    with engine_of(api).begin() as connection:
        connection.execute(
            update(personal_records)
            .where(personal_records.c.work_id == work["id"])
            .values(visibility=visibility)
        )
    base = f"/api/v1/works/{work['id']}/saves"
    assert api.get(f"{base}/suggestions").status_code == 404
    assert api.post(f"{base}/session").status_code == 404


def test_a_test_library_never_looks_at_the_real_home(api: TestClient, settings: Settings) -> None:
    service = api.app.state.service.discovery  # type: ignore[attr-defined]
    for root in service._folders.roots():
        assert root.is_relative_to(settings.data_dir)


# --- save rules using all this ---


def config(client: TestClient, work_id: str, *rules: dict[str, str]) -> Any:
    return client.put(
        f"/api/v1/works/{work_id}/save-config", json={"rules": list(rules), "confirmedNone": False}
    )


def test_a_pattern_rule_backs_up_and_restores_every_matching_file(
    api: TestClient, tmp_path: Path
) -> None:
    work = work_ids(api)[0]
    game = make_game(tmp_path)
    link(api, work["id"], game)
    assert config(api, work["id"], {"kind": "inside", "path": "Save*.rvdata2"}).status_code == 200
    (game / "Save01.rvdata2").write_bytes(b"one")
    (game / "Save02.rvdata2").write_bytes(b"two")
    (game / "Other.rvdata2").write_bytes(b"not a save")
    service = api.app.state.service.updates_game  # type: ignore[attr-defined]
    rules = [{"kind": "inside", "path": "Save*.rvdata2"}]
    assert sorted(item.relative for item in service.saved_files(game, rules)) == [
        "Save01.rvdata2",
        "Save02.rvdata2",
    ]
    backup = service.backup(work["id"], game, rules)
    (game / "Save01.rvdata2").write_bytes(b"changed")
    copy_id = api.get(f"/api/v1/works/{work['id']}/local-copies").json()["copies"][0]["id"]
    assert (
        api.post(f"/api/v1/save-backups/{backup}/restore", json={"copyId": copy_id}).status_code
        == 200
    )
    assert (game / "Save01.rvdata2").read_bytes() == b"one"
    assert (game / "Other.rvdata2").read_bytes() == b"not a save"


@pytest.mark.parametrize(
    "path", ["sa*ve/slot.dat", "../Save*.dat", "*", "*.*", "*.exe", "C:/x/Save*.dat"]
)
def test_a_pattern_that_could_take_too_much_is_refused(
    api: TestClient, tmp_path: Path, path: str
) -> None:
    work = work_ids(api)[0]
    assert config(api, work["id"], {"kind": "inside", "path": path}).status_code == 422


@pytest.mark.parametrize(
    "path",
    [
        "HKCU\\Software\\Microsoft\\Windows",
        "HKCU\\Software\\Classes\\x",
        "HKLM\\Software\\A\\B",
        "HKCU\\Software\\OnlyOneLevel",
        "HKCU\\Software\\A\\..\\Microsoft",
        "HKCU\\Environment",
        "Software\\A\\B",
    ],
)
def test_a_registry_rule_is_only_ever_a_games_own_key(
    api: TestClient, tmp_path: Path, path: str
) -> None:
    work = work_ids(api)[0]
    assert config(api, work["id"], {"kind": "registry", "path": path}).status_code == 422
    with pytest.raises(RegistryRefused):
        subkey_of(path)


def test_registry_saves_back_up_and_restore_like_files(
    api: TestClient, settings: Settings, tmp_path: Path
) -> None:
    work = work_ids(api)[0]
    game = make_game(tmp_path)
    link(api, work["id"], game)
    key = "HKCU\\Software\\Synth\\Game"
    registry = FileRegistry(settings.data_dir / "fake-registry.json")
    registry.write(key, {"values": {"gold_h1": {"type": 4, "data": 100}}, "keys": {}})
    rule = {"kind": "registry", "path": key}
    assert config(api, work["id"], rule).status_code == 200
    service = api.app.state.service.updates_game  # type: ignore[attr-defined]
    backup = service.backup(work["id"], game, [rule])
    registry.write(key, {"values": {"gold_h1": {"type": 4, "data": 1}}, "keys": {}})
    copy_id = api.get(f"/api/v1/works/{work['id']}/local-copies").json()["copies"][0]["id"]
    assert (
        api.post(f"/api/v1/save-backups/{backup}/restore", json={"copyId": copy_id}).status_code
        == 200
    )
    values = registry.read(key)
    assert values is not None
    assert values["values"]["gold_h1"]["data"] == 100


def test_window_settings_do_not_look_like_progress(settings: Settings) -> None:
    registry = FileRegistry(settings.data_dir / "fake-registry.json")
    key = "HKCU\\Software\\Synth\\Game"
    registry.write(
        key,
        {
            "values": {
                "gold_h1": {"type": 4, "data": 1},
                "Screenmanager Resolution Width_h2": {"type": 4, "data": 1920},
            },
            "keys": {},
        },
    )
    held = registry.read(key)
    assert held is not None
    assert list(held["values"]) == ["gold_h1"]
    assert player_values(held) == 1


def test_the_real_registry_round_trip_on_a_throwaway_key() -> None:
    winreg = pytest.importorskip("winreg")
    name = f"LibraryAtlasTest{uuid.uuid4().hex}"
    key = f"HKCU\\Software\\{name}\\Game"
    registry = WindowsRegistry()
    try:
        assert registry.read(key) is None
        registry.write(
            key,
            {
                "values": {
                    "number": {"type": winreg.REG_DWORD, "data": 7},
                    "text": {"type": winreg.REG_SZ, "data": "合成"},
                    "raw": {"type": winreg.REG_BINARY, "data": {"bytes": "AAEC"}},
                    "Screenmanager Width": {"type": winreg.REG_DWORD, "data": 1},
                },
                "keys": {
                    "child": {"values": {"x": {"type": winreg.REG_SZ, "data": "y"}}, "keys": {}}
                },
            },
        )
        held = registry.read(key)
        assert held is not None
        assert held["values"]["number"]["data"] == 7
        assert held["values"]["text"]["data"] == "合成"
        assert held["values"]["raw"]["data"] == {"bytes": "AAEC"}
        assert "Screenmanager Width" not in held["values"]
        assert held["keys"]["child"]["values"]["x"]["data"] == "y"
        assert registry.changed_at(key) is not None
        assert json.dumps(held, ensure_ascii=False)
    finally:
        for sub in (
            f"Software\\{name}\\Game\\child",
            f"Software\\{name}\\Game",
            f"Software\\{name}",
        ):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
            except FileNotFoundError:
                pass
