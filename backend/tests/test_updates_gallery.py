"""Noticing newer versions, and store images. Real API and database; the platform is pretend."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.adapters.dlsite.product import parse_product
from app.core.config import Settings
from app.db.schema import personal_records, source_accounts, works
from tests.conftest import client_for
from tests.test_downloads import Rig, ended, engine_of, first_work, prepare, start


@pytest.fixture
def rig(settings: Settings, tmp_path: Path) -> Rig:
    return Rig(settings, tmp_path)


@pytest.fixture
def api(settings: Settings, rig: Rig) -> Iterator[TestClient]:
    with client_for(settings) as client:
        prepare(client, rig)
        yield client


def resync(client: TestClient, rig: Rig, **control: Any) -> None:
    rig.control.update(control)
    rig.save_control()
    before = client.get("/api/v1/sources/dlsite/sync").json()["job"]["id"]
    assert client.post("/api/v1/sources/dlsite/sync").status_code == 200
    deadline = datetime.now(UTC) + timedelta(seconds=20)
    while datetime.now(UTC) < deadline:
        job = client.get("/api/v1/sources/dlsite/sync").json()["job"]
        if job["id"] != before and job["state"] == "succeeded":
            return
    raise AssertionError("sync did not finish")


def updates(client: TestClient) -> list[str]:
    return [item["workId"] for item in client.get("/api/v1/downloads").json()["updates"]]


def download(client: TestClient, work_id: str, **body: Any) -> dict[str, Any]:
    return ended(client, start(client, work_id, **body)[0]["id"])


# --- newer versions ---


def test_a_changed_work_is_noticed_and_not_downloaded(api: TestClient, rig: Rig) -> None:
    rig.behave(size=1000)
    work = first_work(api)
    task = download(api, work["id"])
    assert updates(api) == []
    resync(api, rig, upgrade="2026-10-30T00:00:00+09:00")
    assert updates(api) == [work["id"]]
    tasks = api.get("/api/v1/downloads").json()["tasks"]
    assert [item["id"] for item in tasks] == [task["id"]]  # Nothing started by itself.


def test_downloading_the_update_settles_it_and_keeps_the_old_file(
    api: TestClient, rig: Rig
) -> None:
    rig.behave(size=1000)
    work = first_work(api)
    download(api, work["id"])
    resync(api, rig, upgrade="2026-10-30T00:00:00+09:00")
    assert download(api, work["id"], again=True)["state"] == "done"
    assert updates(api) == []
    assert len(list((rig.library / work["sourceId"]).iterdir())) == 2


def test_works_never_downloaded_have_no_update(api: TestClient, rig: Rig) -> None:
    resync(api, rig, upgrade="2026-10-30T00:00:00+09:00")
    assert updates(api) == []


def test_an_update_is_not_offered_for_a_file_already_gone(api: TestClient, rig: Rig) -> None:
    rig.behave(size=1000)
    work = first_work(api)
    download(api, work["id"])
    resync(api, rig, upgrade="2026-10-30T00:00:00+09:00")
    for file in (rig.library / work["sourceId"]).iterdir():
        file.unlink()
    assert updates(api) == []


def test_a_hidden_work_is_not_listed_as_updated(api: TestClient, rig: Rig) -> None:
    rig.behave(size=1000)
    work = first_work(api)
    download(api, work["id"])
    resync(api, rig, upgrade="2026-10-30T00:00:00+09:00")
    with engine_of(api).begin() as connection:
        connection.execute(update(personal_records).values(visibility="private"))
    assert updates(api) == []


# --- checking by itself ---


def checker(client: TestClient) -> Any:
    return client.app.state.service.updates  # type: ignore[attr-defined]


def test_checks_at_most_once_a_day(api: TestClient) -> None:
    assert checker(api).tick() is False  # Just synced.
    later = datetime.now(UTC) + timedelta(hours=25)
    assert checker(api).tick(later) is True


def test_can_be_turned_off(api: TestClient) -> None:
    assert api.get("/api/v1/settings/updates").json()["autoCheck"] is True
    response = api.put("/api/v1/settings/updates", json={"autoCheck": False})
    assert response.json()["autoCheck"] is False
    assert checker(api).tick(datetime.now(UTC) + timedelta(days=9)) is False
    # Still off after a restart: it is a setting, not a state of this process.
    assert api.get("/api/v1/settings/updates").json()["autoCheck"] is False


def test_never_signs_in_by_itself(api: TestClient) -> None:
    api.post("/api/v1/sources/dlsite/disconnect")
    with engine_of(api).begin() as connection:
        connection.execute(update(source_accounts).values(last_synced_at=None))
    assert checker(api).tick() is False
    assert api.get("/api/v1/sources/dlsite/connection").json()["state"] != "connected"


def test_a_test_library_starts_no_background_check(api: TestClient) -> None:
    assert checker(api)._thread is None


# --- reading the store record ---


def test_a_store_record_is_read_carefully() -> None:
    product = parse_product(
        [
            {
                "image_main": {"url": "//img.dlsite.jp/main.jpg", "width": "560", "height": "420"},
                "image_samples": [
                    {"url": "//img.dlsite.jp/1.jpg", "width": "1120", "height": "840"},
                    {"url": "//img.dlsite.jp/main.jpg"},
                    {"url": "https://evil.example/x.jpg"},
                    {"url": "file:///C:/Windows/win.ini"},
                    {"url": 5},
                    "not a record",
                ],
                "intro_s": "  简介  ",
            }
        ]
    )
    assert [image.url for image in product.images] == [
        "https://img.dlsite.jp/main.jpg",
        "https://img.dlsite.jp/1.jpg",
    ]
    assert product.images[0].width == 560
    assert product.intro == "简介"


@pytest.mark.parametrize("data", [[], {}, None, "x", [None], [{"image_samples": "x"}]])
def test_an_odd_record_yields_nothing(data: Any) -> None:
    assert parse_product(data).images == ()


# --- the gallery ---


def gallery(client: TestClient, work_id: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/works/{work_id}/gallery")
    assert response.status_code == 200
    result: dict[str, Any] = response.json()
    return result


def test_images_come_through_atlas_addresses(api: TestClient) -> None:
    work = first_work(api)
    data = gallery(api, work["id"])
    assert len(data["images"]) == 6
    first = data["images"][0]
    assert first["url"] == f"/api/v1/works/{work['id']}/gallery/0"
    assert "dlsite" not in str(data["images"])
    image = api.get(first["url"])
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.content.startswith(b"\x89PNG")


def test_an_empty_introduction_is_filled_once(api: TestClient) -> None:
    work = first_work(api)
    assert api.get(f"/api/v1/works/{work['id']}").json()["description"] is None
    assert gallery(api, work["id"])["intro"]
    assert api.get(f"/api/v1/works/{work['id']}").json()["description"]


def test_an_existing_introduction_is_kept(api: TestClient) -> None:
    work = first_work(api)
    with engine_of(api).begin() as connection:
        connection.execute(update(works).where(works.c.id == work["id"]).values(description="原有"))
    assert gallery(api, work["id"])["intro"] == "原有"


def test_a_request_cannot_ask_for_any_other_image(api: TestClient) -> None:
    work = first_work(api)
    gallery(api, work["id"])
    assert api.get(f"/api/v1/works/{work['id']}/gallery/99").status_code == 404
    assert api.get(f"/api/v1/works/{work['id']}/gallery/-1").status_code == 404
    assert api.get(f"/api/v1/works/{work['id']}/gallery/x").status_code == 422


def test_the_list_is_kept_and_a_failed_check_loses_nothing(api: TestClient, rig: Rig) -> None:
    work = first_work(api)
    assert len(gallery(api, work["id"])["images"]) == 6
    rig.control["gallery"] = "offline"
    rig.save_control()
    # Within the week it does not ask at all, so this says nothing went wrong.
    assert gallery(api, work["id"])["unavailable"] is False
    with engine_of(api).begin() as connection:
        connection.execute(
            update(works).where(works.c.id == work["id"]).values(gallery_checked_at=None)
        )
    data = gallery(api, work["id"])
    assert data["unavailable"] is True
    assert len(data["images"]) == 6


def test_offline_with_nothing_known_says_so(api: TestClient, rig: Rig) -> None:
    rig.control["gallery"] = "offline"
    rig.save_control()
    data = gallery(api, first_work(api)["id"])
    assert data["images"] == []
    assert data["unavailable"] is True


def test_a_work_with_no_images_is_simply_empty(api: TestClient, rig: Rig) -> None:
    rig.control["gallery"] = "none"
    rig.save_control()
    data = gallery(api, first_work(api)["id"])
    assert data == {"images": [], "intro": None, "unavailable": False}


@pytest.mark.parametrize("visibility", ["hidden", "private", "quarantined"])
def test_works_outside_ordinary_views_get_no_gallery(api: TestClient, visibility: str) -> None:
    work = first_work(api)
    gallery(api, work["id"])
    with engine_of(api).begin() as connection:
        connection.execute(
            update(personal_records)
            .where(personal_records.c.work_id == work["id"])
            .values(visibility=visibility)
        )
    assert api.get(f"/api/v1/works/{work['id']}/gallery").status_code == 404
    assert api.get(f"/api/v1/works/{work['id']}/gallery/0").status_code == 404


def test_other_platforms_ask_nothing(api: TestClient) -> None:
    work = first_work(api)
    with engine_of(api).begin() as connection:
        connection.execute(update(works).where(works.c.id == work["id"]).values(source_id="steam"))
    assert gallery(api, work["id"])["images"] == []
    with engine_of(api).connect() as connection:
        checked = connection.execute(
            select(works.c.gallery_checked_at).where(works.c.id == work["id"])
        ).scalar()
    assert checked is None
