"""Uninstalling, shortcuts and collections, through the real API and real folders.

The shell is the test library's stand-in: nothing here touches the real desktop or Recycle Bin.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.core.config import Settings
from app.db.schema import game_updates, local_copies, personal_records, works
from tests.conftest import client_for
from tests.test_downloads import Rig, engine_of, prepare, work_ids
from tests.test_library_scan import auto_scan, make_library, work_folders

COPIES = "/api/v1/local-copies"


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


def game_folder(parent: Path, name: str = "作品") -> Path:
    folder = parent / "Library" / "Game" / "社团" / name
    (folder / "存档").mkdir(parents=True)
    (folder / "Game.exe").write_bytes(b"program")
    (folder / "存档" / "save.dat").write_bytes(b"12345")
    return folder


def link(client: TestClient, work_id: str, folder: Path) -> dict[str, Any]:
    # What the form does when there is one program: a second one leaves the choice to the user.
    single = (folder / "Game.exe").is_file() and not (folder / "Other.exe").exists()
    body = {"root": str(folder), **({"entry": "Game.exe"} if single else {})}
    response = client.post(f"/api/v1/works/{work_id}/local-copies", json=body)
    assert response.status_code == 200, response.text
    copies: list[dict[str, Any]] = response.json()["copies"]
    return next(copy for copy in copies if Path(copy["root"]) == folder.resolve())


def preview(client: TestClient, copy_id: str) -> dict[str, Any]:
    response = client.get(f"{COPIES}/{copy_id}/uninstall")
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def uninstall(client: TestClient, copy: dict[str, Any], root: str | None = None) -> Any:
    return client.post(
        f"{COPIES}/{copy['id']}/uninstall", json={"confirmRoot": root or copy["root"]}
    )


def work_of(client: TestClient, work_id: str) -> dict[str, Any]:
    result: dict[str, Any] = client.get(f"/api/v1/works/{work_id}").json()
    return result


# --- installed and launchable ---


def test_a_linked_folder_counts_as_installed_and_says_what_it_can_do(
    api: TestClient, tmp_path: Path
) -> None:
    work = work_ids(api)[0]
    before = work_of(api, work["id"])
    assert before["copyId"] is None
    assert before["launchable"] is False
    copy = link(api, work["id"], game_folder(tmp_path))
    after = work_of(api, work["id"])
    assert after["installed"] is True
    assert after["copyId"] == copy["id"]
    assert after["launchable"] is True
    listed = api.get("/api/v1/works", params={"installed": "installed", "limit": 100}).json()
    assert work["id"] in [item["id"] for item in listed["items"]]
    assert listed["installedCount"] >= 1


def test_a_copy_without_a_main_program_is_not_launchable(api: TestClient, tmp_path: Path) -> None:
    work = work_ids(api)[0]
    folder = game_folder(tmp_path)
    (folder / "Other.exe").write_bytes(b"program")
    link(api, work["id"], folder)
    data = work_of(api, work["id"])
    assert data["copyId"]
    assert data["launchable"] is False


# --- uninstalling ---


def test_uninstalling_moves_the_folder_away_and_forgets_it(
    api: TestClient, tmp_path: Path, settings: Settings
) -> None:
    work = work_ids(api)[0]
    folder = game_folder(tmp_path)
    copy = link(api, work["id"], folder)
    seen = preview(api, copy["id"])
    assert seen["root"] == str(folder.resolve())
    assert seen["files"] == 2
    assert seen["sizeBytes"] == len(b"program") + 5
    assert seen["blocked"] is None
    assert uninstall(api, copy).status_code == 200
    assert not folder.exists()
    assert (folder.parent).is_dir()
    assert api.get(f"/api/v1/works/{work['id']}/local-copies").json()["copies"] == []
    data = work_of(api, work["id"])
    assert data["installed"] is False
    assert data["copyId"] is None
    # It went to the bin, whole, and can be got back.
    binned = list((settings.data_dir / "fake-recycle-bin").iterdir())
    assert (binned[0] / "存档" / "save.dat").read_bytes() == b"12345"


def test_personal_records_and_collections_survive_it(api: TestClient, tmp_path: Path) -> None:
    work = work_ids(api)[0]
    api.post(f"/api/v1/works/{work['id']}/favorite/toggle")
    made = api.post("/api/v1/collections", json={"name": "留着", "workId": work["id"]}).json()
    copy = link(api, work["id"], game_folder(tmp_path))
    assert uninstall(api, copy).status_code == 200
    assert work_of(api, work["id"])["favorite"] is True
    assert api.get("/api/v1/collections").json()["collections"][0]["count"] == 1
    assert made["collections"][0]["contains"] is True


def test_another_copy_takes_over_and_stays(api: TestClient, tmp_path: Path) -> None:
    work = work_ids(api)[0]
    one = link(api, work["id"], game_folder(tmp_path / "d"))
    two_folder = game_folder(tmp_path / "h")
    two = link(api, work["id"], two_folder)
    assert uninstall(api, one).status_code == 200
    assert two_folder.is_dir()
    assert work_of(api, work["id"])["copyId"] == two["id"]
    assert work_of(api, work["id"])["installed"] is True


def test_it_must_be_the_folder_the_user_was_shown(api: TestClient, tmp_path: Path) -> None:
    work = work_ids(api)[0]
    folder = game_folder(tmp_path)
    copy = link(api, work["id"], folder)
    assert uninstall(api, copy, str(tmp_path)).status_code == 409
    assert folder.is_dir()
    assert api.post(f"{COPIES}/{copy['id']}/uninstall", json={}).status_code == 422
    assert folder.is_dir()


def test_a_folder_holding_another_works_copy_is_refused(api: TestClient, tmp_path: Path) -> None:
    one, two = work_ids(api)[:2]
    outer = tmp_path / "Everything"
    inner = game_folder(outer)
    copy = link(api, one["id"], outer)
    link(api, two["id"], inner)
    assert preview(api, copy["id"])["blocked"]
    assert uninstall(api, copy).status_code == 409
    assert (inner / "Game.exe").is_file()


def test_the_library_itself_and_its_layers_are_refused(api: TestClient, tmp_path: Path) -> None:
    from sqlalchemy.dialects.sqlite import insert

    from app.db.schema import scan_roots

    work = work_ids(api)[0]
    folder = game_folder(tmp_path)
    library = tmp_path / "Library"
    with engine_of(api).begin() as connection:
        connection.execute(
            insert(scan_roots).values(
                id="root", path=str(library), path_key=str(library).casefold(), active=1
            )
        )
    for layer in (library, library / "Game", library / "Game" / "社团"):
        copy = link(api, work["id"], layer)
        assert preview(api, copy["id"])["blocked"], layer
        assert uninstall(api, copy).status_code == 409
        api.delete(f"{COPIES}/{copy['id']}")
    assert (folder / "Game.exe").is_file()
    copy = link(api, work["id"], folder)
    assert preview(api, copy["id"])["blocked"] is None


def test_the_chosen_works_folder_is_refused(api: TestClient, rig: Rig) -> None:
    work = work_ids(api)[0]
    copy = link(api, work["id"], rig.works)
    assert preview(api, copy["id"])["blocked"]
    assert uninstall(api, copy).status_code == 409
    assert rig.works.is_dir()


def test_a_link_is_never_followed_out(api: TestClient, tmp_path: Path) -> None:
    winapi = pytest.importorskip("_winapi")
    work = work_ids(api)[0]
    real = game_folder(tmp_path)
    linked = tmp_path / "junction"
    copy = link(api, work["id"], real)
    winapi.CreateJunction(str(real), str(linked))
    with engine_of(api).begin() as connection:
        connection.execute(update(local_copies).values(root_path=str(linked)))
    assert preview(api, copy["id"])["blocked"]
    assert uninstall(api, copy, str(linked)).status_code == 409
    assert (real / "Game.exe").is_file()


def test_links_inside_are_not_counted(api: TestClient, tmp_path: Path) -> None:
    winapi = pytest.importorskip("_winapi")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "big.bin").write_bytes(b"x" * 1000)
    work = work_ids(api)[0]
    folder = game_folder(tmp_path)
    winapi.CreateJunction(str(outside), str(folder / "link"))
    copy = link(api, work["id"], folder)
    assert preview(api, copy["id"])["files"] == 2


def test_an_update_in_progress_holds_it(api: TestClient, tmp_path: Path) -> None:
    work = work_ids(api)[0]
    copy = link(api, work["id"], game_folder(tmp_path))
    with engine_of(api).begin() as connection:
        columns = {column.name for column in game_updates.columns}
        values: dict[str, Any] = {"id": "u", "work_id": work["id"], "state": "unpacking"}
        for column in game_updates.columns:
            if column.name in values or column.nullable or column.server_default is not None:
                continue
            values[column.name] = copy["id"] if column.name == "copy_id" else "x"
        assert "state" in columns
        connection.execute(game_updates.insert().values(**values))
    assert preview(api, copy["id"])["blocked"]
    assert uninstall(api, copy).status_code == 409


def test_a_running_game_holds_it(
    api: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import local_copies as module

    work = work_ids(api)[0]
    folder = game_folder(tmp_path)
    copy = link(api, work["id"], folder)
    monkeypatch.setattr(module, "_in_use", lambda path: True)
    assert "运行" in preview(api, copy["id"])["blocked"]
    assert uninstall(api, copy).status_code == 409
    assert folder.is_dir()


def test_when_the_shell_refuses_nothing_is_forgotten(
    api: TestClient, tmp_path: Path, settings: Settings
) -> None:
    work = work_ids(api)[0]
    folder = game_folder(tmp_path)
    copy = link(api, work["id"], folder)
    (settings.data_dir / "fake-recycle-refuses").write_text("x")
    assert uninstall(api, copy).status_code == 409
    assert folder.is_dir()
    assert len(api.get(f"/api/v1/works/{work['id']}/local-copies").json()["copies"]) == 1


def test_a_folder_got_back_from_the_bin_is_found_again(
    api: TestClient, tmp_path: Path, settings: Settings
) -> None:
    work = work_ids(api)[0]
    root = make_library(tmp_path / "Library", work_folders([work]))
    auto_scan(api, root)
    copies = api.get(f"/api/v1/works/{work['id']}/local-copies").json()["copies"]
    place = Path(copies[0]["root"])
    assert uninstall(api, copies[0]).status_code == 200
    assert api.get(f"/api/v1/works/{work['id']}/local-copies").json()["copies"] == []
    next((settings.data_dir / "fake-recycle-bin").iterdir()).rename(place)
    assert auto_scan(api, root)["job"]["autoLinked"] == 1
    assert len(api.get(f"/api/v1/works/{work['id']}/local-copies").json()["copies"]) == 1


@pytest.mark.parametrize("visibility", ["hidden", "private", "quarantined"])
def test_works_outside_ordinary_views_are_silent(
    api: TestClient, tmp_path: Path, visibility: str
) -> None:
    work = work_ids(api)[0]
    folder = game_folder(tmp_path)
    copy = link(api, work["id"], folder)
    with engine_of(api).begin() as connection:
        connection.execute(
            update(personal_records)
            .where(personal_records.c.work_id == work["id"])
            .values(visibility=visibility)
        )
    assert api.get(f"{COPIES}/{copy['id']}/uninstall").status_code == 404
    assert uninstall(api, copy).status_code == 404
    assert api.post(f"{COPIES}/{copy['id']}/shortcut").status_code == 404
    assert folder.is_dir()


# --- shortcuts ---


def test_a_game_shortcut_starts_the_game(
    api: TestClient, tmp_path: Path, settings: Settings
) -> None:
    work = work_ids(api)[0]
    folder = game_folder(tmp_path)
    copy = link(api, work["id"], folder)
    response = api.post(f"{COPIES}/{copy['id']}/shortcut")
    assert response.status_code == 200
    made = list((settings.data_dir / "fake-desktop").iterdir())
    assert [item.suffix for item in made] == [".lnk"]
    held = json.loads(made[0].read_text(encoding="utf-8"))
    assert held["target"] == str(folder.resolve() / "Game.exe")
    assert held["working"] == str(folder.resolve())
    assert held["icon"] == held["target"]


def test_a_second_shortcut_does_not_replace_the_first(
    api: TestClient, tmp_path: Path, settings: Settings
) -> None:
    work = work_ids(api)[0]
    copy = link(api, work["id"], game_folder(tmp_path))
    for _attempt in range(2):
        assert api.post(f"{COPIES}/{copy['id']}/shortcut").status_code == 200
    assert len(list((settings.data_dir / "fake-desktop").iterdir())) == 2


def test_a_title_cannot_escape_the_desktop(
    api: TestClient, tmp_path: Path, settings: Settings
) -> None:
    work = work_ids(api)[0]
    with engine_of(api).begin() as connection:
        connection.execute(
            update(works).where(works.c.id == work["id"]).values(title='..\\..\\a:b*c?"d<e>|')
        )
    copy = link(api, work["id"], game_folder(tmp_path))
    assert api.post(f"{COPIES}/{copy['id']}/shortcut").status_code == 200
    made = list((settings.data_dir / "fake-desktop").iterdir())
    assert len(made) == 1
    assert not set(made[0].name) & set('\\/:*?"<>|')


def test_a_game_without_a_main_program_gets_no_shortcut(api: TestClient, tmp_path: Path) -> None:
    work = work_ids(api)[0]
    folder = game_folder(tmp_path)
    (folder / "Other.exe").write_bytes(b"program")
    copy = link(api, work["id"], folder)
    assert api.post(f"{COPIES}/{copy['id']}/shortcut").status_code == 409


def test_anything_else_gets_a_shortcut_to_its_folder(
    api: TestClient, tmp_path: Path, settings: Settings
) -> None:
    work = work_ids(api)[0]
    folder = tmp_path / "音声"
    folder.mkdir()
    with engine_of(api).begin() as connection:
        connection.execute(update(works).where(works.c.id == work["id"]).values(kind="audio"))
    copy = link(api, work["id"], folder)
    assert api.post(f"{COPIES}/{copy['id']}/shortcut").status_code == 200
    made = next((settings.data_dir / "fake-desktop").iterdir())
    assert json.loads(made.read_text(encoding="utf-8"))["target"] == str(folder.resolve())


# --- collections ---


def collections(client: TestClient, work_id: str | None = None) -> dict[str, Any]:
    params = {"workId": work_id} if work_id else {}
    result: dict[str, Any] = client.get("/api/v1/collections", params=params).json()
    return result


def test_collections_hold_works_and_filter_the_library(api: TestClient) -> None:
    one, two = work_ids(api)[:2]
    made = api.post("/api/v1/collections", json={"name": " 视觉小说 ", "workId": one["id"]})
    assert made.status_code == 200
    entry = made.json()["collections"][0]
    assert entry["name"] == "视觉小说"
    assert entry["count"] == 1
    assert entry["contains"] is True
    url = f"/api/v1/collections/{entry['id']}/works/{two['id']}"
    assert api.put(url).status_code == 200
    assert api.put(url).status_code == 200
    assert collections(api)["collections"][0]["count"] == 2
    listed = api.get("/api/v1/works", params={"collection": entry["id"], "limit": 100}).json()
    assert {item["id"] for item in listed["items"]} == {one["id"], two["id"]}
    assert listed["filteredCount"] == 2
    assert collections(api, two["id"])["collections"][0]["contains"] is True
    assert api.delete(url).status_code == 200
    assert collections(api, two["id"])["collections"][0]["contains"] is False


def test_names_are_unique_and_required(api: TestClient) -> None:
    assert api.post("/api/v1/collections", json={"name": "Novel"}).status_code == 200
    assert api.post("/api/v1/collections", json={"name": "novel"}).status_code == 409
    assert api.post("/api/v1/collections", json={"name": "   "}).status_code == 422
    assert api.post("/api/v1/collections", json={"name": "x" * 200}).status_code == 422


def test_renaming_keeps_what_is_inside(api: TestClient) -> None:
    work = work_ids(api)[0]
    entry = api.post("/api/v1/collections", json={"name": "旧", "workId": work["id"]}).json()[
        "collections"
    ][0]
    renamed = api.patch(f"/api/v1/collections/{entry['id']}", json={"name": "新"})
    assert renamed.status_code == 200
    assert renamed.json()["collections"][0] == {
        "id": entry["id"],
        "name": "新",
        "count": 1,
        "contains": False,
    }
    assert api.patch("/api/v1/collections/nope", json={"name": "新2"}).status_code == 404


def test_removing_a_collection_leaves_the_works(api: TestClient) -> None:
    work = work_ids(api)[0]
    entry = api.post("/api/v1/collections", json={"name": "去掉", "workId": work["id"]}).json()[
        "collections"
    ][0]
    assert api.delete(f"/api/v1/collections/{entry['id']}").status_code == 200
    assert collections(api)["collections"] == []
    assert work_of(api, work["id"])["id"] == work["id"]


@pytest.mark.parametrize("visibility", ["hidden", "private", "quarantined"])
def test_a_hidden_work_does_not_show_even_as_a_number(api: TestClient, visibility: str) -> None:
    one, two = work_ids(api)[:2]
    entry = api.post("/api/v1/collections", json={"name": "混合", "workId": one["id"]}).json()[
        "collections"
    ][0]
    api.put(f"/api/v1/collections/{entry['id']}/works/{two['id']}")
    api.post(f"/api/v1/works/{one['id']}/favorite/toggle")
    with engine_of(api).begin() as connection:
        connection.execute(
            update(personal_records)
            .where(personal_records.c.work_id == one["id"])
            .values(visibility=visibility)
        )
    data = collections(api)
    assert data["collections"][0]["count"] == 1
    assert data["favorites"] == 0
    listed = api.get("/api/v1/works", params={"collection": entry["id"]}).json()
    assert [item["id"] for item in listed["items"]] == [two["id"]]
    assert api.get("/api/v1/collections", params={"workId": one["id"]}).status_code == 404
    assert api.put(f"/api/v1/collections/{entry['id']}/works/{one['id']}").status_code == 404
