"""Cloud saves through the real API, real adapter code and real files, against a made-up Google at
the HTTP level. Two libraries sharing one fake Drive stand for two computers. No real Google."""

import contextlib
import dataclasses
import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.core.config import Settings
from app.db.schema import cloud_outbox, personal_records, works
from app.services.cloud_saves import Snapshot, classify
from app.testing.fake_drive import FakeDrive, redirect_of
from tests.conftest import client_for
from tests.test_downloads import Rig, engine_of, prepare, work_ids


@dataclass
class Device:
    client: TestClient
    settings: Settings
    work: dict[str, Any]
    folder: Path

    @property
    def save(self) -> Path:
        return self.folder / "save" / "slot1.dat"

    def status(self) -> dict[str, Any]:
        response = self.client.get(f"/api/v1/works/{self.work['id']}/cloud")
        assert response.status_code == 200, response.text
        result: dict[str, Any] = response.json()
        return result

    def backup(self) -> dict[str, Any]:
        response = self.client.post(f"/api/v1/works/{self.work['id']}/cloud/backup")
        assert response.status_code == 200, response.text
        self.flush()
        return self.status()

    def flush(self) -> None:
        self.client.app.state.service.cloud.run_queue()  # type: ignore[attr-defined]

    def restore(self, snapshot: str, *, closed: bool = True) -> httpx.Response:
        return self.client.post(
            f"/api/v1/works/{self.work['id']}/cloud/restore",
            json={"snapshotId": snapshot, "confirmClosed": closed},
        )


def connect(client: TestClient, settings: Settings, code: str = "good") -> None:
    assert (
        client.put(
            "/api/v1/cloud/client", json={"clientId": "client.apps.googleusercontent.com"}
        ).status_code
        == 200
    )
    assert client.post("/api/v1/cloud/connect").status_code == 200
    url = (settings.data_dir / "fake-browser-url").read_text(encoding="utf-8")
    redirect, state = redirect_of(url)
    assert httpx.get(redirect, params={"code": code, "state": state}).status_code == 200


def make_device(settings: Settings, drive: Path, tmp: Path, name: str) -> Iterator[Device]:
    data = dataclasses.replace(settings, data_dir=tmp / name / "data")
    data.data_dir.mkdir(parents=True)
    with client_for(data) as client:
        client.app.state.service.cloud.send_in_background = False  # type: ignore[attr-defined]
        prepare(client, Rig(data, tmp / name))
        work = work_ids(client)[0]
        folder = tmp / name / "game"
        (folder / "save").mkdir(parents=True)
        (folder / "Game.exe").write_bytes(b"program")
        (folder / "save" / "slot1.dat").write_bytes(b"first")
        assert (
            client.post(
                f"/api/v1/works/{work['id']}/local-copies",
                json={"root": str(folder), "entry": "Game.exe"},
            ).status_code
            == 200
        )
        assert (
            client.put(
                f"/api/v1/works/{work['id']}/save-config",
                json={"rules": [{"kind": "inside", "path": "save"}], "confirmedNone": False},
            ).status_code
            == 200
        )
        connect(client, data)
        yield Device(client, data, work, folder)


@pytest.fixture
def drive_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "fake-drive"
    folder.mkdir()
    monkeypatch.setenv("ATLAS_FAKE_DRIVE_DIR", str(folder))
    return folder


@pytest.fixture
def one(settings: Settings, drive_dir: Path, tmp_path: Path) -> Iterator[Device]:
    yield from make_device(settings, drive_dir, tmp_path, "one")


@pytest.fixture
def two(settings: Settings, drive_dir: Path, tmp_path: Path) -> Iterator[Device]:
    yield from make_device(settings, drive_dir, tmp_path, "two")


def fault(drive_dir: Path, on: str, do: str, *, stay: bool = False) -> None:
    path = drive_dir / "faults.json"
    faults = json.loads(path.read_text()) if path.exists() else []
    faults.append({"on": on, "do": do, "stay": stay})
    path.write_text(json.dumps(faults))


def clear_faults(drive_dir: Path) -> None:
    (drive_dir / "faults.json").unlink(missing_ok=True)


def commits(drive_dir: Path) -> list[dict[str, Any]]:
    return [
        item
        for item in FakeDrive(drive_dir).files_of_account()
        if item["appProperties"].get("kind") == "commit"
    ]


# --- deciding, from history and content alone ---


def snap(id_: str, digest: str, *parents: str) -> Snapshot:
    return Snapshot(id_, parents, digest, {}, f"c-{id_}")


@pytest.mark.parametrize(
    ("local", "base", "base_digest", "history", "expected"),
    [
        ("x", None, None, [], "local_only"),
        (None, None, None, [], "empty"),
        ("a", "A", "a", [snap("A", "a")], "synced"),
        ("a", None, None, [snap("A", "a")], "synced"),
        ("x", "A", "a", [snap("A", "a")], "local_changed"),
        ("a", "A", "a", [snap("A", "a"), snap("B", "b", "A")], "cloud_update"),
        (None, None, None, [snap("A", "a")], "cloud_update"),
        ("x", "A", "a", [snap("A", "a"), snap("B", "b", "A")], "conflict"),
        ("x", None, None, [snap("A", "a")], "conflict"),
        ("a", "A", "a", [snap("A", "a"), snap("B", "b", "A"), snap("C", "c", "A")], "conflict"),
        ("b", "A", "a", [snap("A", "a"), snap("B", "b", "A")], "synced"),
        ("a", "gone", "z", [snap("A", "a"), snap("B", "b", "A")], "conflict"),
    ],
)
def test_the_decision(
    local: str | None,
    base: str | None,
    base_digest: str | None,
    history: list[Snapshot],
    expected: str,
) -> None:
    assert classify(local, base, base_digest, history)[0] == expected


# --- signing in ---


def test_not_connected_says_so(settings: Settings, drive_dir: Path, tmp_path: Path) -> None:
    with client_for(settings) as client:
        prepare(client, Rig(settings, tmp_path))
        work = work_ids(client)[0]
        assert client.get(f"/api/v1/works/{work['id']}/cloud").json()["state"] == "not_connected"
        assert client.post("/api/v1/cloud/connect").status_code == 409


def test_sign_in_asks_for_the_least_and_uses_pkce(one: Device) -> None:
    url = (one.settings.data_dir / "fake-browser-url").read_text(encoding="utf-8")
    query = httpx.URL(url).params
    assert query["scope"] == "https://www.googleapis.com/auth/drive.file"
    assert query["code_challenge_method"] == "S256"
    assert query["redirect_uri"].startswith("http://127.0.0.1:")
    status = one.client.get("/api/v1/cloud").json()
    assert status["connected"] is True
    assert status["accountName"]
    assert "refresh" not in json.dumps(status)


def test_an_answer_with_the_wrong_state_or_a_replay_does_nothing(
    settings: Settings, drive_dir: Path, tmp_path: Path
) -> None:
    with client_for(settings) as client:
        prepare(client, Rig(settings, tmp_path))
        client.put("/api/v1/cloud/client", json={"clientId": "client"})
        client.post("/api/v1/cloud/connect")
        url = (settings.data_dir / "fake-browser-url").read_text(encoding="utf-8")
        redirect, state = redirect_of(url)
        assert httpx.get(redirect, params={"code": "good", "state": "forged"}).status_code == 400
        assert client.get("/api/v1/cloud").json()["connected"] is False
        assert httpx.get(redirect, params={"code": "good", "state": state}).status_code == 200
        assert client.get("/api/v1/cloud").json()["connected"] is True


@pytest.mark.parametrize(
    "params", [{"error": "access_denied"}, {"code": "refused"}], ids=["cancelled", "refused"]
)
def test_refusal_leaves_it_disconnected_and_says_so(
    settings: Settings, drive_dir: Path, tmp_path: Path, params: dict[str, str]
) -> None:
    with client_for(settings) as client:
        prepare(client, Rig(settings, tmp_path))
        client.put("/api/v1/cloud/client", json={"clientId": "client"})
        client.post("/api/v1/cloud/connect")
        url = (settings.data_dir / "fake-browser-url").read_text(encoding="utf-8")
        redirect, state = redirect_of(url)
        httpx.get(redirect, params={**params, "state": state})
        status = client.get("/api/v1/cloud").json()
        assert status["connected"] is False
        assert status["problem"]


def test_an_old_sign_in_cannot_finish_after_a_new_one_began(
    settings: Settings, drive_dir: Path, tmp_path: Path
) -> None:
    with client_for(settings) as client:
        prepare(client, Rig(settings, tmp_path))
        client.put("/api/v1/cloud/client", json={"clientId": "client"})
        client.post("/api/v1/cloud/connect")
        first = (settings.data_dir / "fake-browser-url").read_text(encoding="utf-8")
        client.post("/api/v1/cloud/connect")
        redirect, state = redirect_of(first)
        # Its port closes with it, or at the very least it is refused on the way out.
        with contextlib.suppress(httpx.HTTPError):
            httpx.get(redirect, params={"code": "good", "state": state}, timeout=2)
        assert client.get("/api/v1/cloud").json()["connected"] is False


def test_a_revoked_grant_asks_to_sign_in_again_and_keeps_local_saves(
    one: Device, drive_dir: Path
) -> None:
    one.backup()
    (drive_dir / "revoked").write_text("x")
    one.client.app.state.service.cloud._access = None  # type: ignore[attr-defined]
    assert one.status()["state"] == "needs_auth"
    assert one.save.read_bytes() == b"first"


def test_disconnecting_stops_it_and_deletes_nothing(one: Device, drive_dir: Path) -> None:
    one.backup()
    held = len(commits(drive_dir))
    assert one.client.post("/api/v1/cloud/disconnect").status_code == 200
    assert one.status()["state"] == "not_connected"
    assert one.client.post(f"/api/v1/works/{one.work['id']}/cloud/backup").status_code == 409
    assert len(commits(drive_dir)) == held
    assert one.save.read_bytes() == b"first"


# --- a snapshot going up ---


def test_a_backup_goes_up_and_can_be_seen_again_after_a_restart(
    settings: Settings, drive_dir: Path, tmp_path: Path
) -> None:
    gen = make_device(settings, drive_dir, tmp_path, "solo")
    device = next(gen)
    assert device.status()["state"] == "local_only"
    data = device.backup()
    assert data["state"] == "synced"
    assert data["history"][0]["files"] == 1
    assert data["history"][0]["isCurrent"] is True
    gen.close()
    with client_for(device.settings) as client:
        again = client.get(f"/api/v1/works/{device.work['id']}/cloud").json()
        assert again["state"] == "synced"
        assert len(again["history"]) == 1


def test_only_what_the_rules_name_goes_up(one: Device, drive_dir: Path) -> None:
    one.backup()
    fake = FakeDrive(drive_dir)
    data = next(
        item for item in fake.files_of_account() if item["appProperties"].get("kind") == "data"
    )
    import io
    import zipfile

    names = zipfile.ZipFile(io.BytesIO(fake.blob(data["id"]))).namelist()
    assert names == ["0/slot1.dat"]


def test_the_data_is_committed_only_after_it_is_checked(one: Device, drive_dir: Path) -> None:
    (one.client.post(f"/api/v1/works/{one.work['id']}/cloud/backup"))
    fault(drive_dir, "upload_end", "corrupt")
    one.flush()
    assert commits(drive_dir) == []
    one.flush()
    assert len(commits(drive_dir)) == 1
    assert one.status()["state"] == "synced"


def test_a_lost_answer_makes_neither_a_duplicate_nor_a_false_success(
    one: Device, drive_dir: Path
) -> None:
    one.client.post(f"/api/v1/works/{one.work['id']}/cloud/backup")
    fault(drive_dir, "upload_end", "lose_answer")
    cloud = one.client.app.state.service.cloud  # type: ignore[attr-defined]
    cloud._sleep = lambda seconds: None
    one.flush()
    one.flush()
    fake = FakeDrive(drive_dir)
    data = [i for i in fake.files_of_account() if i["appProperties"].get("kind") == "data"]
    assert len(data) == 1
    assert len(commits(drive_dir)) == 1


def test_offline_keeps_it_waiting_and_it_goes_later(one: Device, drive_dir: Path) -> None:
    fault(drive_dir, "any", "offline", stay=True)
    response = one.client.post(f"/api/v1/works/{one.work['id']}/cloud/backup")
    assert response.status_code == 200
    one.flush()
    status = one.status()
    assert status["state"] == "offline"
    assert status["queue"]["count"] == 1
    clear_faults(drive_dir)
    one.flush()
    assert one.status()["state"] == "synced"


def test_a_full_drive_reports_and_keeps_the_snapshot_waiting(one: Device, drive_dir: Path) -> None:
    fault(drive_dir, "upload_start", "quota")
    one.client.post(f"/api/v1/works/{one.work['id']}/cloud/backup")
    one.flush()
    assert one.status()["state"] == "quota"
    assert one.client.post(f"/api/v1/works/{one.work['id']}/cloud/retry").status_code == 200
    one.flush()
    assert one.status()["state"] == "synced"


def test_a_queue_survives_a_restart(settings: Settings, drive_dir: Path, tmp_path: Path) -> None:
    gen = make_device(settings, drive_dir, tmp_path, "solo")
    device = next(gen)
    fault(drive_dir, "any", "offline", stay=True)
    device.client.post(f"/api/v1/works/{device.work['id']}/cloud/backup")
    gen.close()
    clear_faults(drive_dir)
    with client_for(device.settings) as client:
        client.app.state.service.cloud.send_in_background = False  # type: ignore[attr-defined]
        client.app.state.service.cloud.run_queue()  # type: ignore[attr-defined]
        assert client.get(f"/api/v1/works/{device.work['id']}/cloud").json()["state"] == "synced"


def test_nothing_changed_means_nothing_new(one: Device, drive_dir: Path) -> None:
    one.backup()
    one.backup()
    assert len(commits(drive_dir)) == 1


def test_no_saves_never_uploads_an_empty_snapshot(one: Device, drive_dir: Path) -> None:
    one.backup()
    one.save.unlink()
    assert one.client.post(f"/api/v1/works/{one.work['id']}/cloud/backup").status_code == 409
    assert len(commits(drive_dir)) == 1
    # And absence is not an instruction: the cloud copy is simply there to take back.
    assert one.status()["state"] == "cloud_update"


def test_a_save_changing_while_packing_is_refused(
    one: Device, drive_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import cloud_saves

    real = cloud_saves.zipfile.ZipFile.write

    def write_and_change(self: Any, filename: Any, arcname: Any = None, *args: Any) -> None:
        real(self, filename, arcname, *args)
        one.save.write_bytes(b"still being written")

    monkeypatch.setattr(cloud_saves.zipfile.ZipFile, "write", write_and_change)
    response = one.client.post(f"/api/v1/works/{one.work['id']}/cloud/backup")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "cloud_changing"
    assert commits(drive_dir) == []


def test_unconfigured_is_not_the_same_as_no_saves(one: Device) -> None:
    url = f"/api/v1/works/{one.work['id']}/save-config"
    one.client.put(url, json={"rules": [], "confirmedNone": False})
    assert one.status()["state"] == "unconfigured"
    one.client.put(url, json={"rules": [], "confirmedNone": True})
    assert one.status()["state"] == "no_saves"


def test_a_failing_listing_is_never_read_as_an_empty_cloud(one: Device, drive_dir: Path) -> None:
    one.backup()
    fault(drive_dir, "list", "fail")
    assert one.status()["state"] == "error"


def test_listing_reads_every_page(one: Device, drive_dir: Path) -> None:
    for index in range(5):
        one.save.write_bytes(f"version {index}".encode())
        one.backup()
    assert len(one.status()["history"]) == 5


def test_another_folder_of_the_same_name_is_not_claimed(one: Device, drive_dir: Path) -> None:
    fake = FakeDrive(drive_dir)
    files = (
        json.loads((drive_dir / "files.json").read_text())
        if (drive_dir / "files.json").exists()
        else {}
    )
    files["theirs"] = {
        "id": "theirs",
        "name": "Library Atlas 云存档",
        "appProperties": {},
        "owner": fake.account(),
        "createdTime": "0",
    }
    (drive_dir / "files.json").write_text(json.dumps(files))
    one.backup()
    data = next(i for i in fake.files_of_account() if i["appProperties"].get("kind") == "data")
    assert data["parents"] != ["theirs"]


# --- restoring ---


def test_restore_protects_what_is_here_then_puts_it_back(one: Device) -> None:
    first = one.backup()["history"][0]["id"]
    one.save.write_bytes(b"second")
    one.backup()
    response = one.restore(first)
    assert response.status_code == 200
    assert one.save.read_bytes() == b"first"
    backups = one.client.get(f"/api/v1/works/{one.work['id']}/update").json()["backups"]
    assert len(backups) >= 1


def test_restore_needs_the_game_closed(one: Device) -> None:
    first = one.backup()["history"][0]["id"]
    one.save.write_bytes(b"newer")
    assert one.restore(first, closed=False).status_code == 409
    assert one.save.read_bytes() == b"newer"


def test_a_damaged_download_touches_nothing(one: Device, drive_dir: Path) -> None:
    first = one.backup()["history"][0]["id"]
    one.save.write_bytes(b"newer")
    fault(drive_dir, "download", "corrupt")
    response = one.restore(first)
    assert response.status_code == 409
    assert one.save.read_bytes() == b"newer"


def test_a_hostile_snapshot_cannot_write_outside(
    one: Device, drive_dir: Path, tmp_path: Path
) -> None:
    import hashlib
    import io
    import zipfile

    first = one.backup()["history"][0]["id"]
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("0/../../../escaped.dat", b"evil")
    blob = payload.getvalue()
    fake = FakeDrive(drive_dir)
    commit = commits(drive_dir)[0]
    manifest = json.loads(fake.blob(commit["id"]))
    entry = {
        "rule": 0,
        "relative": "../../../escaped.dat",
        "stored": "0/../../../escaped.dat",
        "size": 4,
        "sha256": hashlib.sha256(b"evil").hexdigest(),
    }
    data_id = manifest["data"]["file_id"]
    (drive_dir / "blobs" / data_id).write_bytes(blob)
    manifest["data"].update(size=len(blob), md5=hashlib.md5(blob).hexdigest())  # noqa: S324
    manifest["files"] = [entry]
    (drive_dir / "blobs" / commit["id"]).write_text(json.dumps(manifest), encoding="utf-8")
    one.client.app.state.service.cloud._manifests.clear()  # type: ignore[attr-defined]
    assert one.restore(first).status_code == 409
    assert not list(tmp_path.rglob("escaped.dat"))
    assert one.save.read_bytes() == b"first"


def test_a_snapshot_from_a_newer_atlas_is_not_guessed_at(one: Device, drive_dir: Path) -> None:
    first = one.backup()["history"][0]["id"]
    fake = FakeDrive(drive_dir)
    commit = commits(drive_dir)[0]
    manifest = json.loads(fake.blob(commit["id"]))
    manifest["schema"] = 99
    (drive_dir / "blobs" / commit["id"]).write_text(json.dumps(manifest), encoding="utf-8")
    one.client.app.state.service.cloud._manifests.clear()  # type: ignore[attr-defined]
    assert one.status()["history"][0]["restorable"] is False
    assert one.restore(first).status_code == 409


def test_changed_save_locations_block_restore(one: Device) -> None:
    first = one.backup()["history"][0]["id"]
    one.client.put(
        f"/api/v1/works/{one.work['id']}/save-config",
        json={"rules": [{"kind": "inside", "path": "elsewhere"}], "confirmedNone": False},
    )
    response = one.restore(first)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "cloud_config"


def test_files_a_snapshot_does_not_list_are_left_alone(one: Device) -> None:
    first = one.backup()["history"][0]["id"]
    extra = one.folder / "save" / "slot2.dat"
    extra.write_bytes(b"made since")
    assert one.restore(first).status_code == 200
    assert extra.read_bytes() == b"made since"


def test_an_interrupted_restore_is_said_on_the_next_look(
    one: Device, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = one.backup()["history"][0]["id"]
    cloud = one.client.app.state.service.cloud  # type: ignore[attr-defined]

    def crash(*args: Any) -> None:
        raise SystemError("the power went")

    monkeypatch.setattr(cloud, "_write", crash)
    assert one.restore(first).status_code == 500
    assert one.status()["state"] == "restore_interrupted"
    monkeypatch.undo()
    assert one.restore(first).status_code == 200
    assert one.status()["state"] == "synced"


# --- two computers ---


def test_a_second_computer_sees_and_takes_the_first_ones_save(one: Device, two: Device) -> None:
    two.save.unlink()
    one.save.write_bytes(b"from one")
    made = one.backup()["history"][0]
    seen = two.status()
    assert seen["state"] == "cloud_update"
    assert seen["history"][0]["thisDevice"] is False
    assert two.restore(made["id"]).status_code == 200
    assert two.save.read_bytes() == b"from one"
    assert two.status()["state"] == "synced"
    # Back the other way, in a line: no conflict.
    two.save.write_bytes(b"from two")
    two.backup()
    assert one.status()["state"] == "cloud_update"


def test_two_computers_changing_from_one_snapshot_leave_two_branches(
    one: Device, two: Device, drive_dir: Path
) -> None:
    base = one.backup()["history"][0]["id"]
    assert two.restore(base).status_code == 200
    one.save.write_bytes(b"branch one")
    two.save.write_bytes(b"branch two")
    one.backup()
    two.backup()
    assert len(commits(drive_dir)) == 3
    a, b = one.status(), two.status()
    assert a["state"] == "conflict"
    assert b["state"] == "conflict"
    heads = [item for item in a["history"] if item["isHead"]]
    assert len(heads) == 2
    # Neither is lost, and neither computer's own save was touched.
    assert one.save.read_bytes() == b"branch one"
    assert two.save.read_bytes() == b"branch two"
    other = next(item for item in heads if not item["thisDevice"])
    assert one.restore(other["id"]).status_code == 200
    assert one.save.read_bytes() == b"branch two"


def test_choosing_settles_it_on_both_computers_and_keeps_both_branches(
    one: Device, two: Device, drive_dir: Path
) -> None:
    base = one.backup()["history"][0]["id"]
    two.restore(base)
    one.save.write_bytes(b"branch one")
    two.save.write_bytes(b"branch two")
    one.backup()
    two.backup()
    chosen = next(i for i in one.status()["history"] if i["isHead"] and not i["thisDevice"])
    response = one.client.post(
        f"/api/v1/works/{one.work['id']}/cloud/resolve",
        json={"keep": chosen["id"], "confirmClosed": True},
    )
    assert response.status_code == 200, response.text
    assert one.save.read_bytes() == b"branch two"
    assert one.status()["state"] == "synced"
    assert two.status()["state"] == "synced"
    assert len(commits(drive_dir)) == 4
    assert all(i["restorable"] for i in one.status()["history"])


def test_keeping_the_local_save_settles_it_too(one: Device, two: Device) -> None:
    base = one.backup()["history"][0]["id"]
    two.restore(base)
    one.save.write_bytes(b"branch one")
    two.save.write_bytes(b"branch two")
    one.backup()
    two.backup()
    response = one.client.post(
        f"/api/v1/works/{one.work['id']}/cloud/resolve",
        json={"keep": "local", "confirmClosed": True},
    )
    assert response.status_code == 200, response.text
    one.flush()
    assert one.status()["state"] == "synced"
    assert one.save.read_bytes() == b"branch one"
    assert two.status()["state"] == "cloud_update"


def test_same_content_on_both_is_no_conflict(one: Device, two: Device) -> None:
    one.backup()
    assert two.status()["state"] == "synced"


def test_device_ids_differ_between_computers(one: Device, two: Device, drive_dir: Path) -> None:
    one.backup()
    two.save.write_bytes(b"other")
    two.backup()
    fake = FakeDrive(drive_dir)
    devices = {json.loads(fake.blob(item["id"]))["device"]["id"] for item in commits(drive_dir)}
    assert len(devices) == 2


# --- accounts ---


def test_another_account_sees_nothing_and_a_queue_never_crosses_over(
    one: Device, drive_dir: Path
) -> None:
    one.backup()
    fault(drive_dir, "any", "offline", stay=True)
    one.save.write_bytes(b"for account a")
    one.client.post(f"/api/v1/works/{one.work['id']}/cloud/backup")
    clear_faults(drive_dir)
    (drive_dir / "account").write_text("account-b")
    connect(one.client, one.settings)
    one.flush()
    assert commits(drive_dir) == []
    assert one.status()["history"] == []
    (drive_dir / "account").write_text("account-a")
    connect(one.client, one.settings)
    one.flush()
    assert len(commits(drive_dir)) == 2


# --- privacy ---


@pytest.mark.parametrize("visibility", ["hidden", "private", "quarantined"])
def test_works_outside_ordinary_views_are_silent(one: Device, visibility: str) -> None:
    with engine_of(one.client).begin() as connection:
        connection.execute(
            update(personal_records)
            .where(personal_records.c.work_id == one.work["id"])
            .values(visibility=visibility)
        )
    base = f"/api/v1/works/{one.work['id']}/cloud"
    assert one.client.get(base).status_code == 404
    assert one.client.post(f"{base}/backup").status_code == 404


def test_no_title_or_path_goes_to_drive(one: Device, drive_dir: Path) -> None:
    with engine_of(one.client).begin() as connection:
        connection.execute(update(works).values(title="私人标题哨兵"))
    one.backup()
    fake = FakeDrive(drive_dir)
    text = json.dumps(fake.files_of_account(), ensure_ascii=False)
    manifest = fake.blob(commits(drive_dir)[0]["id"]).decode()
    for held in (text, manifest):
        assert "私人标题哨兵" not in held
        assert str(one.folder) not in held
        assert str(one.folder).replace("\\", "\\\\") not in held


def test_the_token_is_in_no_database_row_or_response(one: Device) -> None:
    one.backup()
    with engine_of(one.client).connect() as connection:
        rows = connection.execute(select(cloud_outbox)).all()
    assert "refresh" not in str(rows)
    assert "refresh" not in one.client.get("/api/v1/cloud").text
    assert "access" not in one.status().__repr__().replace("accessible", "")


# --- after playing ---


def test_after_play_backup_is_off_by_default_and_works_when_on(
    one: Device, drive_dir: Path
) -> None:
    cloud = one.client.app.state.service.cloud  # type: ignore[attr-defined]
    cloud.watch_times = (0.05, 0.01, 0.01)
    states = [True, True, False]
    cloud._in_use = lambda path: states.pop(0) if states else False
    cloud._sleep = lambda seconds: threading.Event().wait(seconds)
    program = one.folder / "Game.exe"
    cloud.game_started(one.work["id"], program)
    assert threading.active_count() >= 1
    assert one.status()["queue"]["count"] == 0
    assert commits(drive_dir) == []
    assert (
        one.client.put(
            "/api/v1/cloud/options", json={"autoCheck": False, "autoBackup": True}
        ).status_code
        == 200
    )
    cloud._watch(one.work["id"], program)
    one.flush()
    assert len(commits(drive_dir)) == 1


def test_a_game_never_seen_running_gets_no_guess(one: Device, drive_dir: Path) -> None:
    cloud = one.client.app.state.service.cloud  # type: ignore[attr-defined]
    cloud.watch_times = (0.02, 0.01, 0.0)
    cloud._in_use = lambda path: False
    cloud._sleep = lambda seconds: threading.Event().wait(seconds)
    one.client.put("/api/v1/cloud/options", json={"autoCheck": False, "autoBackup": True})
    cloud._watch(one.work["id"], one.folder / "Game.exe")
    one.flush()
    assert commits(drive_dir) == []


# --- the Drive client itself ---


def test_a_dropped_connection_continues_rather_than_starting_over(
    one: Device, drive_dir: Path
) -> None:
    from app.adapters.google.drive import _CHUNK, DriveClient

    drive = DriveClient(
        lambda force: "token", FakeDrive(drive_dir).transport(), sleep=lambda seconds: None
    )
    fault(drive_dir, "chunk", "drop")
    content = b"x" * (_CHUNK + 1024)
    made = drive.upload("big.bin", "parent", {"kind": "test"}, content, "application/octet-stream")
    assert int(made["size"]) == len(content)
    assert FakeDrive(drive_dir).blob(made["id"]) == content
