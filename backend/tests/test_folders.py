"""Folder settings. The test profile's stand-ins answer the chooser and open nothing."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.system.folder_dialog import DialogFolderPicker, ExplorerFolderOpener
from app.core.config import Settings
from app.db.bootstrap import open_database
from app.services.dlsite_factory import build_folder_service
from tests.conftest import client_for, write_headers

BASE = "/api/v1/settings/folders"


@pytest.fixture
def api(settings: Settings) -> Iterator[TestClient]:
    with client_for(settings) as client:
        client.headers.update(write_headers(client))
        yield client


def folder(client: TestClient, kind: str) -> dict:
    items = client.get(BASE).json()["folders"]
    return next(item for item in items if item["kind"] == kind)


def test_defaults_create_nothing_and_ask_for_a_download_folder(
    api: TestClient, settings: Settings
) -> None:
    assert folder(api, "library") == {
        "kind": "library",
        "path": None,
        "isDefault": True,
        "status": "not_set",
    }
    cache = folder(api, "download_cache")
    assert cache["isDefault"] is True
    assert cache["status"] == "ok"
    assert not (settings.data_dir / "download-cache").exists()


def test_chosen_folder_survives_restart(settings: Settings, tmp_path: Path) -> None:
    target = tmp_path / "作品 文件夹"
    target.mkdir()
    with client_for(settings) as client:
        client.headers.update(write_headers(client))
        assert client.put(f"{BASE}/library", json={"path": str(target)}).status_code == 200
    with client_for(settings) as client:
        current = folder(client, "library")
    assert current["path"] == str(target.resolve())
    assert current["isDefault"] is False
    assert current["status"] == "ok"


def test_invalid_folders_are_refused_and_change_nothing(
    api: TestClient, settings: Settings, tmp_path: Path
) -> None:
    good = tmp_path / "good"
    good.mkdir()
    file = tmp_path / "a-file"
    file.write_text("x", encoding="utf-8")
    inside = settings.data_dir / "inside"
    inside.mkdir()
    for bad in (
        "relative/dir",
        str(tmp_path / "missing"),
        str(file),
        str(settings.data_dir),
        str(inside),
    ):
        response = api.put(f"{BASE}/library", json={"path": bad})
        assert response.status_code == 422, bad
        assert response.json()["error"]["code"] == "folder_invalid"
    assert folder(api, "library")["status"] == "not_set"


def test_system_folders_are_refused(api: TestClient) -> None:
    system = Path(__import__("os").environ.get("SystemRoot", "C:/Windows"))
    if not system.is_dir():
        pytest.skip("no system folder here")
    assert api.put(f"{BASE}/library", json={"path": str(system)}).status_code == 422


def test_both_kinds_cannot_share_a_folder(api: TestClient, tmp_path: Path) -> None:
    api.put(f"{BASE}/library", json={"path": str(tmp_path)})
    response = api.put(f"{BASE}/download_cache", json={"path": str(tmp_path)})
    assert response.status_code == 422
    assert "同一个" in response.json()["error"]["message"]


def test_a_folder_gone_missing_is_reported_not_recreated(api: TestClient, tmp_path: Path) -> None:
    target = tmp_path / "unplugged"
    target.mkdir()
    api.put(f"{BASE}/library", json={"path": str(target)})
    target.rmdir()
    assert folder(api, "library")["status"] == "missing"
    response = api.post(f"{BASE}/library/open")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "folder_missing"
    assert not target.exists()


def test_open_needs_a_set_folder_and_creates_only_the_default_cache(
    api: TestClient, settings: Settings
) -> None:
    assert api.post(f"{BASE}/library/open").json()["error"]["code"] == "folder_not_set"
    assert api.post(f"{BASE}/download_cache/open").status_code == 200
    assert (settings.data_dir / "download-cache").is_dir()


def test_picker_sets_the_choice_and_cancel_changes_nothing(
    api: TestClient, settings: Settings, tmp_path: Path
) -> None:
    control = settings.data_dir / "fake-platform.json"
    assert folder(api, "library")["status"] == "not_set"
    api.post(f"{BASE}/library/pick")
    assert folder(api, "library")["status"] == "not_set"
    control.write_text(json.dumps({"pick": str(tmp_path)}), encoding="utf-8")
    assert api.post(f"{BASE}/library/pick").status_code == 200
    assert folder(api, "library")["path"] == str(tmp_path.resolve())


def test_requests_cannot_name_what_to_open(api: TestClient, tmp_path: Path) -> None:
    response = api.post(f"{BASE}/nope/open")
    assert response.status_code == 422
    assert api.put(f"{BASE}/nope", json={"path": str(tmp_path)}).status_code == 422
    extra = api.put(f"{BASE}/library", json={"path": str(tmp_path), "other": 1})
    assert extra.status_code == 422


def test_folder_changes_need_the_local_boundary(settings: Settings, tmp_path: Path) -> None:
    with client_for(settings) as client:
        assert client.put(f"{BASE}/library", json={"path": str(tmp_path)}).status_code == 403
        assert client.post(f"{BASE}/library/pick").status_code == 403
        assert client.post(f"{BASE}/library/open").status_code == 403
        token = write_headers(client)["X-Atlas-CSRF"]
        forged = client.post(
            f"{BASE}/library/open",
            headers={"Origin": "https://evil.example", "X-Atlas-CSRF": token},
        )
        assert forged.status_code == 403


def test_paths_stay_out_of_the_log(
    settings: Settings, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    target = tmp_path / "私人路径XYZ"
    target.mkdir()
    with caplog.at_level("INFO", logger="atlas"), client_for(settings) as client:
        client.headers.update(write_headers(client))
        client.put(f"{BASE}/library", json={"path": str(target)})
        client.get(BASE)
    assert "私人路径XYZ" not in caplog.text


def test_real_profile_uses_the_real_chooser(tmp_path: Path) -> None:
    data = tmp_path / "real"
    data.mkdir()
    real = Settings(profile="real", data_dir=data, port=8765, static_dir=None)
    opened = open_database(real.database_path, real.backup_dir, "real")
    try:
        service = build_folder_service(real, opened.engine)
    finally:
        opened.engine.dispose()
    assert isinstance(service._picker, DialogFolderPicker)
    assert isinstance(service._opener, ExplorerFolderOpener)
