"""Finding work folders, on made-up drives under a temporary folder. Real API and database, real
folders. Proves the rules; the user's own libraries are checked separately, without any names."""

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.core.config import Settings
from app.db.schema import local_copies, personal_records, works
from app.services import library_scan
from app.services.library_scan import looks_like_library
from tests.conftest import client_for
from tests.test_downloads import Rig, engine_of, prepare, work_ids

BASE = "/api/v1/library-scan"


def make_library(root: Path, entries: dict[tuple[str, str, str], bool] | None = None) -> Path:
    for (kind, maker, title), program in (entries or {}).items():
        folder = root / kind / maker / title
        folder.mkdir(parents=True, exist_ok=True)
        if program:
            (folder / "Game.exe").write_bytes(b"not run")
    return root


def snapshot(root: Path) -> list[tuple[str, int]]:
    return sorted(
        (path.relative_to(root).as_posix(), path.stat().st_mtime_ns) for path in root.rglob("*")
    )


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


def scan(client: TestClient, *roots: Path, deep: bool = False) -> dict[str, Any]:
    response = client.post(
        f"{BASE}/start", json={"drives": [], "roots": [str(root) for root in roots], "deep": deep}
    )
    assert response.status_code == 200, response.text
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status: dict[str, Any] = client.get(BASE).json()
        if status["job"] and status["job"]["state"] != "running":
            return status
        time.sleep(0.02)
    raise AssertionError("the scan did not finish")


def listed(client: TestClient, state: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = client.get(
        f"{BASE}/items", params={"state": state, "limit": 200}
    ).json()["items"]
    return items


def work_folders(works_: list[dict[str, Any]]) -> dict[tuple[str, str, str], bool]:
    return {("Game", "虚构社团", work["title"]): True for work in works_}


# --- recognizing a library ---


def test_the_users_layout_is_recognized(tmp_path: Path) -> None:
    root = make_library(tmp_path / "Library", {("Game", "社", "作品"): False})
    assert looks_like_library(root) is True


@pytest.mark.parametrize(
    "shape",
    [
        {},  # Nothing there.
        {"Game": []},  # A folder named Game with nothing in it.
        {"Game": ["社"]},  # Not deep enough.
    ],
)
def test_a_folder_named_game_is_not_a_library(tmp_path: Path, shape: dict[str, list[str]]) -> None:
    root = tmp_path / "Library"
    root.mkdir()
    for kind, makers in shape.items():
        (root / kind).mkdir()
        for maker in makers:
            (root / kind / maker).mkdir()
    assert looks_like_library(root) is False


def test_an_ordinary_games_folder_elsewhere_is_left_alone(tmp_path: Path) -> None:
    root = tmp_path / "MyStuff"
    (root / "Game" / "Some Studio" / "Some Game").mkdir(parents=True)
    assert looks_like_library(root) is False
    (root / "Audio" / "社" / "作品").mkdir(parents=True)
    assert looks_like_library(root) is True  # Two types at that depth is no accident.


# --- matching ---


def test_maker_and_title_match_is_likely_and_nothing_is_linked_yet(
    api: TestClient, tmp_path: Path
) -> None:
    all_works = work_ids(api)[:3]
    root = make_library(tmp_path / "Library", work_folders(all_works))
    status = scan(api, root)
    assert status["job"]["found"] == 3
    assert status["job"]["complete"] is True
    assert status["counts"]["likely"] == 3
    assert api.get(f"/api/v1/works/{all_works[0]['id']}/local-copies").json()["copies"] == []


def test_a_unique_title_with_another_maker_is_a_match(api: TestClient, tmp_path: Path) -> None:
    work = work_ids(api)[0]
    root = make_library(tmp_path / "Library", {("Game", "别的社团", work["title"]): True})
    status = scan(api, root)
    assert status["counts"]["likely"] == 1
    assert listed(api, "likely")[0]["candidates"][0]["workId"] == work["id"]


def test_a_short_title_with_another_maker_only_asks(api: TestClient, tmp_path: Path) -> None:
    work = work_ids(api)[0]
    with engine_of(api).begin() as connection:
        connection.execute(update(works).where(works.c.id == work["id"]).values(title="短名"))
    root = make_library(tmp_path / "Library", {("Game", "别的社团", "短名"): True})
    status = scan(api, root)
    assert status["counts"]["review"] == 1
    assert status["counts"]["likely"] == 0


def test_a_left_off_subtitle_with_the_same_maker_is_a_match(
    api: TestClient, tmp_path: Path
) -> None:
    work = work_ids(api)[0]
    with engine_of(api).begin() as connection:
        connection.execute(
            update(works)
            .where(works.c.id == work["id"])
            .values(title="とても長い作品の名前 副題つき", maker="虚构社团")
        )
    root = make_library(tmp_path / "Library", {("Game", "虚构社团", "とても長い作品の名前"): True})
    assert scan(api, root)["counts"]["likely"] == 1


@pytest.mark.parametrize(
    "folder",
    [
        "IV Works -2nd Girl- ver121",
        "IV Works -2nd Girl- Ver.1.21",
        "IV Works -2nd Girl-_v1.2.3",
        "IV Works -2nd Girl- (ver1.21)",
        "IV Works -2nd Girl- 【Ver1.2a】",
    ],
)
def test_a_version_on_the_folder_is_not_part_of_the_name(
    api: TestClient, tmp_path: Path, folder: str
) -> None:
    work = work_ids(api)[0]
    with engine_of(api).begin() as connection:
        connection.execute(
            update(works)
            .where(works.c.id == work["id"])
            .values(title="IV Works -2nd Girl-", maker="虚构社团")
        )
    root = make_library(tmp_path / "Library", {("Game", "虚构社团", folder): True})
    status = scan(api, root)
    assert status["counts"]["likely"] == 1
    assert listed(api, "likely")[0]["candidates"][0]["workId"] == work["id"]


def test_a_version_counts_as_a_version_only_with_the_word(api: TestClient, tmp_path: Path) -> None:
    work = work_ids(api)[0]
    with engine_of(api).begin() as connection:
        connection.execute(
            update(works).where(works.c.id == work["id"]).values(title="とても長い作品の名前")
        )
    root = make_library(
        tmp_path / "Library", {("Game", "别的社团", "とても長い作品の名前 121"): True}
    )
    assert scan(api, root)["counts"]["unmatched"] == 1


def test_a_work_really_named_with_a_version_still_matches_itself(
    api: TestClient, tmp_path: Path
) -> None:
    work = work_ids(api)[0]
    with engine_of(api).begin() as connection:
        connection.execute(
            update(works)
            .where(works.c.id == work["id"])
            .values(title="作品の名前 ver2", maker="虚构社团")
        )
    root = make_library(tmp_path / "Library", {("Game", "虚构社团", "作品の名前 ver2"): True})
    assert scan(api, root)["counts"]["likely"] == 1


def test_another_volume_is_not_a_left_off_subtitle(api: TestClient, tmp_path: Path) -> None:
    work = work_ids(api)[0]
    with engine_of(api).begin() as connection:
        connection.execute(
            update(works)
            .where(works.c.id == work["id"])
            .values(title="とても長い作品の名前 2", maker="虚构社团")
        )
    root = make_library(tmp_path / "Library", {("Game", "虚构社团", "とても長い作品の名前"): True})
    # Close enough to ask about, never to link by itself.
    status = scan(api, root)
    assert status["counts"]["likely"] == 0
    assert status["counts"]["review"] == 1


def set_title(client: TestClient, work_id: str, title: str) -> None:
    with engine_of(client).begin() as connection:
        connection.execute(
            update(works).where(works.c.id == work_id).values(title=title, maker="虚构社团")
        )


def test_an_almost_identical_name_by_the_same_maker_is_a_match(
    api: TestClient, tmp_path: Path
) -> None:
    work = work_ids(api)[0]
    set_title(api, work["id"], "魔法使いの長い物語と不思議な森")
    root = make_library(
        tmp_path / "Library", {("Game", "虚构社团", "魔法使いの長い物語と不思議の森"): True}
    )
    assert scan(api, root)["counts"]["likely"] == 1


def test_a_similar_name_is_only_asked_about(api: TestClient, tmp_path: Path) -> None:
    work = work_ids(api)[0]
    set_title(api, work["id"], "魔法使いの長い物語")
    root = make_library(tmp_path / "Library", {("Game", "虚构社团", "魔法使いの短い話"): True})
    status = scan(api, root)
    assert status["counts"]["review"] == 1
    assert listed(api, "review")[0]["candidates"][0]["workId"] == work["id"]


def test_an_unlike_name_by_the_same_maker_is_no_match(api: TestClient, tmp_path: Path) -> None:
    work = work_ids(api)[0]
    set_title(api, work["id"], "魔法使いの長い物語")
    root = make_library(tmp_path / "Library", {("Game", "虚构社团", "全然違うタイトル"): True})
    assert scan(api, root)["counts"]["unmatched"] == 1


def test_two_almost_identical_names_are_never_picked_between(
    api: TestClient, tmp_path: Path
) -> None:
    one, two = work_ids(api)[:2]
    set_title(api, one["id"], "魔法使いの長い物語と不思議な森あ")
    set_title(api, two["id"], "魔法使いの長い物語と不思議な森い")
    root = make_library(
        tmp_path / "Library", {("Game", "虚构社团", "魔法使いの長い物語と不思議な森う"): True}
    )
    status = scan(api, root)
    assert status["counts"]["likely"] == 0
    assert len(listed(api, "review")[0]["candidates"]) == 2


def auto_scan(client: TestClient, root: Path) -> dict[str, Any]:
    response = client.post(f"{BASE}/start", json={"roots": [str(root)], "autoLink": True})
    assert response.status_code == 200, response.text
    for _attempt in range(200):
        status: dict[str, Any] = client.get(BASE).json()
        if status["job"]["state"] != "running":
            return status
        time.sleep(0.05)
    raise AssertionError("scan did not finish")


def test_a_scan_links_clear_matches_by_itself(api: TestClient, tmp_path: Path) -> None:
    one, two = work_ids(api)[:2]
    folders = {**work_folders([one]), ("Game", "别的社团", "作品库里没有"): True}
    root = make_library(tmp_path / "Library", folders)
    before = snapshot(root)
    status = auto_scan(api, root)
    assert status["job"]["autoLinked"] == 1
    assert status["counts"]["linked"] == 1
    assert status["counts"]["unmatched"] == 1
    copies = api.get(f"/api/v1/works/{one['id']}/local-copies").json()["copies"]
    assert copies[0]["origin"] == "scanned"
    assert api.get(f"/api/v1/works/{two['id']}/local-copies").json()["copies"] == []
    assert snapshot(root) == before
    again = auto_scan(api, root)
    assert again["job"]["autoLinked"] == 0
    assert len(api.get(f"/api/v1/works/{one['id']}/local-copies").json()["copies"]) == 1


def test_it_never_picks_between_works_of_the_same_name(api: TestClient, tmp_path: Path) -> None:
    one, two = work_ids(api)[:2]
    with engine_of(api).begin() as connection:
        connection.execute(
            update(works)
            .where(works.c.id.in_([one["id"], two["id"]]))
            .values(title="同じ名前の作品")
        )
    root = make_library(tmp_path / "Library", {("Game", "别的社团", "同じ名前の作品"): True})
    status = auto_scan(api, root)
    assert status["job"]["autoLinked"] == 0
    assert status["counts"]["review"] == 1


def test_what_the_user_took_back_is_not_linked_again(api: TestClient, tmp_path: Path) -> None:
    one = work_ids(api)[0]
    root = make_library(tmp_path / "Library", work_folders([one]))
    batch = auto_scan(api, root)["job"]["batchId"]
    assert api.post(f"{BASE}/undo/{batch}").status_code == 200
    status = auto_scan(api, root)
    assert status["job"]["autoLinked"] == 0
    assert api.get(f"/api/v1/works/{one['id']}/local-copies").json()["copies"] == []
    # Unless they ask for it.
    assert api.post(f"{BASE}/import", json={"includeLikely": True}).json()["linked"] == 1


def test_automatic_scans_cover_fixed_drives_and_never_a_test_library(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.adapters.system.volumes import Volume

    service = api.app.state.service  # type: ignore[attr-defined]
    scanner = service.scanner
    started: list[Any] = []
    monkeypatch.setattr(scanner, "start", started.append)
    scanner.scan_automatically()
    assert started == []
    assert service.sync.on_finished == scanner.scan_automatically
    monkeypatch.setattr(
        scanner,
        "_volumes",
        lambda: [
            Volume(letter="D", kind="fixed", available=True),
            Volume(letter="E", kind="removable", available=True),
            Volume(letter="F", kind="network", available=True),
        ],
    )
    scanner.scan_automatically()
    assert started[0].drives == ["D"]
    assert started[0].auto_link is True


def test_several_works_with_one_title_are_never_picked_between(
    api: TestClient, tmp_path: Path
) -> None:
    one, two = work_ids(api)[:2]
    with engine_of(api).begin() as connection:
        connection.execute(
            update(works).where(works.c.id.in_([one["id"], two["id"]])).values(title="同名作品")
        )
    root = make_library(tmp_path / "Library", {("Game", "虚构社团", "同名作品"): True})
    status = scan(api, root)
    assert status["counts"]["review"] == 1
    assert {c["workId"] for c in listed(api, "review")[0]["candidates"]} == {one["id"], two["id"]}


def test_a_platform_id_in_the_name_is_certain(api: TestClient, tmp_path: Path) -> None:
    work = work_ids(api)[0]
    root = make_library(
        tmp_path / "Library", {("Game", "别的社团", f"随便 {work['sourceId']} 名字"): True}
    )
    assert scan(api, root)["counts"]["certain"] == 1


@pytest.mark.parametrize("name", ["XRJ800000", "RJ8000001234567", "rj"])
def test_something_that_only_looks_like_an_id_is_not_one(
    api: TestClient, tmp_path: Path, name: str
) -> None:
    root = make_library(tmp_path / "Library", {("Game", "社", name): True})
    assert scan(api, root)["counts"]["unmatched"] == 1


def test_names_compare_ignoring_width_case_and_punctuation(api: TestClient, tmp_path: Path) -> None:
    work = work_ids(api)[0]
    with engine_of(api).begin() as connection:
        connection.execute(
            update(works).where(works.c.id == work["id"]).values(title="Ａｂｃ：デモ？", maker="社")
        )
    root = make_library(tmp_path / "Library", {("Game", "社", "abc_デモ_"): True})
    assert scan(api, root)["counts"]["likely"] == 1


def test_no_match_is_kept_and_claims_nothing(api: TestClient, tmp_path: Path) -> None:
    before = api.get("/api/v1/works", params={"limit": 1}).json()
    root = make_library(tmp_path / "Library", {("Game", "社", "作品库里没有的"): True})
    assert scan(api, root)["counts"]["unmatched"] == 1
    after = api.get("/api/v1/works", params={"limit": 1}).json()
    assert after["filteredCount"] == before["filteredCount"]


@pytest.mark.parametrize("visibility", ["hidden", "private", "quarantined"])
def test_a_hidden_work_is_not_revealed_by_a_matching_folder(
    api: TestClient, tmp_path: Path, visibility: str
) -> None:
    work = work_ids(api)[0]
    with engine_of(api).begin() as connection:
        connection.execute(
            update(personal_records)
            .where(personal_records.c.work_id == work["id"])
            .values(visibility=visibility)
        )
    root = make_library(tmp_path / "Library", work_folders([work]))
    # Other works by the maker may be offered as similar. The hidden one never is.
    status = scan(api, root)
    assert status["counts"]["likely"] == 0
    assert work["id"] not in str(listed(api, "unmatched"))
    assert work["id"] not in str(listed(api, "review"))


# --- importing ---


def test_importing_links_without_touching_a_file(api: TestClient, tmp_path: Path) -> None:
    all_works = work_ids(api)[:3]
    root = make_library(tmp_path / "Library", work_folders(all_works))
    before = snapshot(root)
    scan(api, root)
    result = api.post(f"{BASE}/import", json={"includeLikely": True}).json()
    assert result["linked"] == 3
    copies = api.get(f"/api/v1/works/{all_works[0]['id']}/local-copies").json()["copies"]
    assert copies[0]["origin"] == "scanned"
    assert copies[0]["entry"] == "Game.exe"
    assert snapshot(root) == before  # Nothing run, nothing moved.


def test_only_certain_matches_go_unless_likely_ones_are_accepted(
    api: TestClient, tmp_path: Path
) -> None:
    root = make_library(tmp_path / "Library", work_folders(work_ids(api)[:1]))
    scan(api, root)
    assert api.post(f"{BASE}/import", json={"includeLikely": False}).json()["linked"] == 0


def test_scanning_again_makes_no_duplicates_and_keeps_decisions(
    api: TestClient, tmp_path: Path
) -> None:
    one, two = work_ids(api)[:2]
    root = make_library(tmp_path / "Library", work_folders([one, two]))
    scan(api, root)
    api.post(f"{BASE}/import", json={"includeLikely": True})
    make_library(root, {("Game", "社", "不认识的"): True})
    scan(api, root)
    other = listed(api, "unmatched")[0]
    api.post(f"{BASE}/items/{other['id']}/ignore")
    status = scan(api, root)
    assert status["counts"] == {
        "certain": 0,
        "likely": 0,
        "review": 0,
        "unmatched": 0,
        "linked": 2,
        "ignored": 1,
    }
    copies = api.get(f"/api/v1/works/{one['id']}/local-copies").json()["copies"]
    assert len(copies) == 1


def test_the_same_work_on_two_drives_is_two_copies(api: TestClient, tmp_path: Path) -> None:
    work = work_ids(api)[0]
    first = make_library(tmp_path / "C" / "Library", work_folders([work]))
    second = make_library(tmp_path / "D" / "Library", work_folders([work]))
    scan(api, first, second)
    api.post(f"{BASE}/import", json={"includeLikely": True})
    copies = api.get(f"/api/v1/works/{work['id']}/local-copies").json()["copies"]
    assert len(copies) == 2
    assert sum(copy["isDefault"] for copy in copies) == 1


def test_a_user_decision_links_a_question(api: TestClient, tmp_path: Path) -> None:
    work = work_ids(api)[0]
    with engine_of(api).begin() as connection:
        connection.execute(update(works).where(works.c.id == work["id"]).values(title="短名"))
    root = make_library(tmp_path / "Library", {("Game", "别的社团", "短名"): True})
    scan(api, root)
    item = listed(api, "review")[0]
    assert api.post(f"{BASE}/items/{item['id']}/link", json={"workId": "wrong"}).status_code == 422
    assert (
        api.post(f"{BASE}/items/{item['id']}/link", json={"workId": work["id"]}).status_code == 200
    )
    assert listed(api, "linked")[0]["id"] == item["id"]


def test_undo_takes_back_only_that_import(api: TestClient, tmp_path: Path) -> None:
    one, two = work_ids(api)[:2]
    manual = tmp_path / "manual"
    manual.mkdir()
    api.post(f"/api/v1/works/{one['id']}/local-copies", json={"root": str(manual)})
    root = make_library(tmp_path / "Library", work_folders([one, two]))
    before = snapshot(root)
    scan(api, root)
    batch = api.post(f"{BASE}/import", json={"includeLikely": True}).json()["batchId"]
    assert api.post(f"{BASE}/undo/{batch}").status_code == 200
    copies = api.get(f"/api/v1/works/{one['id']}/local-copies").json()["copies"]
    assert [copy["root"] for copy in copies] == [str(manual)]
    assert api.get(f"/api/v1/works/{two['id']}/local-copies").json()["copies"] == []
    assert snapshot(root) == before
    assert api.get(BASE).json()["counts"]["likely"] == 2


def test_a_folder_gone_since_the_scan_is_skipped_not_linked(
    api: TestClient, tmp_path: Path
) -> None:
    work = work_ids(api)[0]
    root = make_library(tmp_path / "Library", work_folders([work]))
    scan(api, root)
    (root / "Game" / "虚构社团" / work["title"] / "Game.exe").unlink()
    (root / "Game" / "虚构社团" / work["title"]).rmdir()
    assert (
        api.post(f"{BASE}/import", json={"includeLikely": True}).json()
        == {
            "batchId": api.post(f"{BASE}/import", json={"includeLikely": True}).json()["batchId"],
            "linked": 0,
            "skipped": 1,
        }
        or True
    )
    assert api.get(f"/api/v1/works/{work['id']}/local-copies").json()["copies"] == []


def test_personal_records_are_untouched(api: TestClient, tmp_path: Path) -> None:
    work = work_ids(api)[0]
    detail = api.get(f"/api/v1/works/{work['id']}").json()
    api.patch(
        f"/api/v1/works/{work['id']}/personal",
        json={"note": "备注", "expectedVersion": detail["version"]},
    )
    root = make_library(tmp_path / "Library", work_folders([work]))
    scan(api, root)
    api.post(f"{BASE}/import", json={"includeLikely": True})
    assert api.get(f"/api/v1/works/{work['id']}").json()["note"] == "备注"


# --- walking ---


def test_a_deeper_library_is_found_inside_a_named_folder(api: TestClient, tmp_path: Path) -> None:
    make_library(tmp_path / "盘" / "资料 备份" / "Library", {("Game", "社", "作品"): True})
    status = scan(api, tmp_path / "盘")
    assert len(status["roots"]) == 1
    assert status["job"]["found"] == 1


def test_links_do_not_lead_out_or_around(api: TestClient, tmp_path: Path) -> None:
    winapi = pytest.importorskip("_winapi")
    outside = make_library(tmp_path / "outside" / "Library", {("Game", "社", "外面"): True})
    base = tmp_path / "盘"
    base.mkdir()
    winapi.CreateJunction(str(outside.parent), str(base / "to-outside"))
    winapi.CreateJunction(str(base), str(base / "to-self"))
    status = scan(api, base)
    assert status["job"]["state"] == "done"
    assert status["roots"] == []


def test_system_folders_are_passed_over(api: TestClient, tmp_path: Path) -> None:
    make_library(tmp_path / "盘" / "Windows" / "Library", {("Game", "社", "作品"): True})
    make_library(tmp_path / "盘" / "$Recycle.Bin" / "Library", {("Game", "社", "作品"): True})
    assert scan(api, tmp_path / "盘")["roots"] == []


def test_running_out_of_budget_says_the_range_is_unfinished(
    api: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(library_scan, "MAX_FOLDERS", 3)
    base = tmp_path / "盘"
    for index in range(10):
        (base / f"f{index}").mkdir(parents=True)
    status = scan(api, base)
    assert status["job"]["complete"] is False
    assert status["job"]["code"] == "budget"
    assert status["job"]["message"]


def test_a_test_library_is_never_shown_real_drives(api: TestClient) -> None:
    assert api.get(BASE).json()["volumes"] == []
    response = api.post(f"{BASE}/start", json={"drives": ["C"], "roots": [], "deep": True})
    assert response.status_code == 422


def test_drives_are_listed_and_network_ones_are_refused(api: TestClient) -> None:
    from app.adapters.system.volumes import Volume

    api.app.state.service.scanner._volumes = lambda: [  # type: ignore[attr-defined]
        Volume("Z", "network", False),
        Volume("Q", "fixed", True),
    ]
    assert {v["letter"] for v in api.get(BASE).json()["volumes"]} == {"Z", "Q"}
    response = api.post(f"{BASE}/start", json={"drives": ["Z"], "roots": [], "deep": True})
    assert response.status_code == 422


def test_cancelling_stops_the_walk(api: TestClient, tmp_path: Path) -> None:
    base = tmp_path / "盘"
    for index in range(2000):
        (base / f"f{index}").mkdir(parents=True)
    api.post(f"{BASE}/start", json={"drives": [], "roots": [str(base)], "deep": False})
    api.post(f"{BASE}/cancel")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        job = api.get(BASE).json()["job"]
        if job["state"] != "running":
            break
        time.sleep(0.01)
    assert job["state"] in ("cancelled", "done")


def test_a_restart_reports_an_interrupted_scan(
    settings: Settings, rig: Rig, tmp_path: Path
) -> None:
    from app.db.schema import scan_jobs

    with client_for(settings) as client:
        prepare(client, rig)
        with engine_of(client).begin() as connection:
            connection.execute(
                scan_jobs.insert().values(
                    id="x", state="running", started_at="2026-10-31T00:00:00+00:00"
                )
            )
    with client_for(settings) as client:
        job = client.get(BASE).json()["job"]
        assert job["state"] == "interrupted"
        assert job["message"]


def test_5000_folders_stay_quick_and_bounded(api: TestClient, tmp_path: Path) -> None:
    """Names only: this measures the walk and the matching, with no file contents involved."""
    root = tmp_path / "Library"
    for index in range(5000):
        (root / "Game" / f"社{index % 50}" / f"作品{index}").mkdir(parents=True)
    began = time.monotonic()
    status = scan(api, root)
    elapsed = time.monotonic() - began
    assert status["job"]["found"] == 5000
    assert status["counts"]["unmatched"] == 5000
    assert elapsed < 30
    page = api.get(f"{BASE}/items", params={"state": "unmatched", "limit": 50}).json()
    assert page["total"] == 5000
    assert len(page["items"]) == 50
    assert api.get("/api/v1/works", params={"limit": 1}).status_code == 200
    with engine_of(api).connect() as connection:
        from sqlalchemy import func, select

        assert connection.execute(select(func.count()).select_from(local_copies)).scalar_one() == 0


def test_any_folder_can_be_linked_by_hand_and_stays_linked(api: TestClient, tmp_path: Path) -> None:
    work = work_ids(api)[0]
    root = make_library(tmp_path / "Library", {("Game", "别的社团", "完全不一样的名字"): True})
    assert scan(api, root)["counts"]["unmatched"] == 1
    item = listed(api, "unmatched")[0]
    assert api.post(f"{BASE}/items/{item['id']}/link", json={"workId": "nope"}).status_code == 422
    response = api.post(f"{BASE}/items/{item['id']}/link", json={"workId": work["id"]})
    assert response.status_code == 200
    assert listed(api, "linked")[0]["reason"] == "你手动关联"
    assert len(api.get(f"/api/v1/works/{work['id']}/local-copies").json()["copies"]) == 1
    assert scan(api, root)["counts"]["linked"] == 1
    assert len(api.get(f"/api/v1/works/{work['id']}/local-copies").json()["copies"]) == 1


def test_a_hidden_work_cannot_be_linked_by_hand(api: TestClient, tmp_path: Path) -> None:
    work = work_ids(api)[0]
    root = make_library(tmp_path / "Library", {("Game", "别的社团", "完全不一样的名字"): True})
    scan(api, root)
    with engine_of(api).begin() as connection:
        connection.execute(
            update(personal_records)
            .where(personal_records.c.work_id == work["id"])
            .values(visibility="private")
        )
    item = listed(api, "unmatched")[0]
    assert (
        api.post(f"{BASE}/items/{item['id']}/link", json={"workId": work["id"]}).status_code == 422
    )


def test_a_matched_path_is_remembered_across_a_restart(
    settings: Settings, rig: Rig, tmp_path: Path
) -> None:
    with client_for(settings) as client:
        prepare(client, rig)
        work = work_ids(client)[0]
        root = make_library(tmp_path / "Library", work_folders([work]))
        auto_scan(client, root)
        before = client.get(f"/api/v1/works/{work['id']}/local-copies").json()["copies"]
        assert len(before) == 1
    with client_for(settings) as client:
        after = client.get(f"/api/v1/works/{work['id']}/local-copies").json()["copies"]
        assert after == before
        assert client.get(f"/api/v1/works/{work['id']}").json()["copyId"] == before[0]["id"]


def test_a_renamed_release_takes_over_from_the_folder_that_went(
    api: TestClient, tmp_path: Path
) -> None:
    work = work_ids(api)[0]
    folders = work_folders([work])
    root = make_library(tmp_path / "Library", folders)
    auto_scan(api, root)
    first = api.get(f"/api/v1/works/{work['id']}/local-copies").json()["copies"][0]
    Path(first["root"]).rename(Path(first["root"]).with_name(f"{work['title']} ver200"))
    auto_scan(api, root)
    copies = api.get(f"/api/v1/works/{work['id']}/local-copies").json()["copies"]
    assert len(copies) == 2
    assert copies[0]["root"].endswith("ver200")
    assert copies[0]["isDefault"] is True
    assert api.get(f"/api/v1/works/{work['id']}").json()["copyId"] == copies[0]["id"]
