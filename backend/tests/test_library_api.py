import json
from collections import Counter

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.db.bootstrap import open_database
from app.domain.text import sort_title
from app.repositories.works import (
    SourceMetadata,
    WorkFile,
    replace_work_files,
    set_visibility,
    upsert_source_metadata,
)
from app.testing.synthetic import PRIVATE_SENTINELS, build_samples
from tests.conftest import client_for, seed_library, write_headers

SENTINEL_IDS = [f"syn-{visibility}" for visibility in PRIVATE_SENTINELS]
SENTINEL_MARK = "SENTINEL"


def works(client: TestClient, **params) -> dict:
    response = client.get("/api/v1/works", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def all_items(client: TestClient, **params) -> list[dict]:
    items: list[dict] = []
    offset = 0
    while True:
        page = works(client, offset=offset, limit=37, **params)
        items.extend(page["items"])
        offset += 37
        if offset >= page["filteredCount"]:
            return items


def test_page_contract_and_counts(client: TestClient) -> None:
    page = works(client, limit=10)
    assert len(page["items"]) == 10
    assert page["filteredCount"] == page["totalVisible"] == 120
    assert sum(page["kindCounts"].values()) == 120
    item = page["items"][0]
    assert set(item) >= {
        "id", "platform", "sourceId", "kind", "title", "status", "installed", "playtimeMinutes",
        "favorite", "cover", "addedAt", "lastPlayedAt", "capabilities", "file",
    }  # fmt: skip
    assert item["visibility"] == "normal"


ALL_SORTS = [
    "curated",
    "name-asc",
    "name-desc",
    "playtime-desc",
    "playtime-asc",
    "added-desc",
    "added-asc",
    "maker-asc",
    "maker-desc",
    "genre-asc",
    "genre-desc",
    "rating-desc",
    "rating-asc",
    "release-desc",
    "release-asc",
    "size-desc",
    "size-asc",
]


@pytest.mark.parametrize("sort", ALL_SORTS)
def test_pagination_never_skips_or_repeats(client: TestClient, sort: str) -> None:
    ids = [item["id"] for item in all_items(client, sort=sort)]
    assert len(ids) == 120
    assert len(set(ids)) == 120


def test_unknown_playtime_stays_last_in_both_directions(client: TestClient) -> None:
    for sort in ("playtime-desc", "playtime-asc"):
        values = [item["playtimeMinutes"] for item in all_items(client, sort=sort)]
        known = [value for value in values if value is not None]
        assert values == known + [None] * (len(values) - len(known))
        assert known == sorted(known, reverse=sort == "playtime-desc")
    assert any(value is None for value in values)
    assert 0 in known  # Zero and unknown are kept apart.


def test_name_sort_is_natural_and_width_insensitive() -> None:
    assert sorted(["第10卷", "第2卷"], key=sort_title) == ["第2卷", "第10卷"]
    assert sort_title("Ａｔｌａｓ") == sort_title("atlas")


def test_combined_filters_are_intersections(client: TestClient) -> None:
    items = all_items(client, platform="dlsite", kind="game")
    assert items and all(i["platform"] == "dlsite" and i["kind"] == "game" for i in items)
    non_game = all_items(client, kind="non-game")
    assert non_game and all(item["kind"] != "game" for item in non_game)
    assert len(non_game) + works(client, kind="game")["filteredCount"] == 120
    installed = works(client, installed="installed")
    absent = works(client, installed="not-installed")
    # Unknown local state is neither: it must not read as "not on this machine".
    assert installed["filteredCount"] + absent["filteredCount"] < 120


def test_search_is_literal_and_normalized(client: TestClient) -> None:
    assert works(client, search="同名样本")["filteredCount"] == 2
    assert works(client, search="Ｔｈｅ　Ｖｅｒｙ")["filteredCount"] == 1
    assert works(client, search="The Very Long")["filteredCount"] == 1
    assert works(client, search="the very long")["filteredCount"] == 1
    # LIKE wildcards and SQL fragments are ordinary characters.
    assert works(client, search="%")["filteredCount"] == 0
    assert works(client, search="_")["filteredCount"] == 0
    assert works(client, search="' OR 1=1 --")["filteredCount"] == 0


def test_same_source_id_on_two_platforms_stays_two_works(client: TestClient) -> None:
    steam = client.get("/api/v1/works/syn-steam-1001").json()
    dlsite = client.get("/api/v1/works/syn-dlsite-1001").json()
    assert steam["sourceId"] == dlsite["sourceId"] == "1001"
    assert steam["title"] == dlsite["title"]
    assert steam["platform"] != dlsite["platform"]
    assert steam["playtimeMinutes"] == 725
    assert dlsite["playtimeMinutes"] is None


def test_one_work_keeps_many_files(client: TestClient) -> None:
    detail = client.get("/api/v1/works/syn-multipart").json()
    assert len(detail["files"]) == 3
    assert [file["partIndex"] for file in detail["files"]] == [1, 2, None]
    assert detail["files"][2]["sizeBytes"] is None
    assert detail["files"][2]["downloadState"] == "unknown"
    assert works(client, search="多文件样本")["filteredCount"] == 1


def test_missing_fields_stay_null(client: TestClient) -> None:
    detail = client.get("/api/v1/works/syn-unknown").json()
    assert detail["kind"] == "other"
    assert detail["maker"] is None
    assert detail["genre"] is None
    assert detail["releaseDate"] is None
    assert detail["playtimeMinutes"] is None
    assert detail["achievements"] is None
    assert detail["installed"] is None
    assert detail["cover"]["kind"] == "missing"
    assert detail["capabilities"] == {"download": None, "extract": None, "officialViewerOnly": None}


# --- personal edits ---


def test_edit_round_trip_and_list_reflects_it(client: TestClient, writer: dict) -> None:
    response = client.patch(
        "/api/v1/works/syn-multipart/personal",
        json={
            "status": "playing",
            "rating": 5,
            "note": "  <b>第一卷</b>\n很好  ",
            "favorite": True,
        },
        headers=writer,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "playing"
    assert body["rating"] == 5
    assert body["note"] == "<b>第一卷</b>\n很好"  # Stored as plain text, trimmed, not sanitized.
    assert body["favorite"] is True
    assert body["version"] == 2
    listed = works(client, favoritesOnly="true", status="playing")
    assert [item["id"] for item in listed["items"]] == ["syn-multipart"]
    assert listed["favoriteCount"] == 1


def test_rating_can_be_cleared_but_other_fields_keep_their_values(
    client: TestClient, writer: dict
) -> None:
    url = "/api/v1/works/syn-multipart/personal"
    client.patch(url, json={"rating": 3, "note": "keep"}, headers=writer)
    cleared = client.patch(url, json={"rating": None}, headers=writer).json()
    assert cleared["rating"] is None
    assert cleared["note"] == "keep"


@pytest.mark.parametrize(
    "body",
    [
        {"rating": 0},
        {"rating": 6},
        {"rating": 2.5},
        {"rating": "3"},
        {"status": "bogus"},
        {"note": "x" * 1001},
        {"favorite": "yes"},
        {"visibility": "normal"},
        {"title": "renamed"},
        {"installed": True},
    ],
)
def test_invalid_edits_are_rejected_without_echo(
    client: TestClient, writer: dict, body: dict
) -> None:
    response = client.patch("/api/v1/works/syn-multipart/personal", json=body, headers=writer)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_request"
    assert "x" * 50 not in response.text
    assert client.get("/api/v1/works/syn-multipart").json()["version"] == 1


def test_empty_edit_is_refused(client: TestClient, writer: dict) -> None:
    response = client.patch("/api/v1/works/syn-multipart/personal", json={}, headers=writer)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "no_changes"


def test_stale_expected_version_conflicts_and_changes_nothing(
    client: TestClient, writer: dict
) -> None:
    url = "/api/v1/works/syn-multipart/personal"
    client.patch(url, json={"note": "第一次"}, headers=writer)
    stale = client.patch(url, json={"note": "迟到的旧内容", "expectedVersion": 1}, headers=writer)
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "version_conflict"
    assert client.get("/api/v1/works/syn-multipart").json()["note"] == "第一次"
    fresh = client.patch(url, json={"note": "第二次", "expectedVersion": 2}, headers=writer)
    assert fresh.status_code == 200
    assert fresh.json()["version"] == 3


def test_toggle_favorite_flips_and_counts(client: TestClient, writer: dict) -> None:
    url = "/api/v1/works/syn-multipart/favorite/toggle"
    assert client.post(url, headers=writer).json()["favorite"] is True
    assert works(client)["favoriteCount"] == 1
    assert client.post(url, headers=writer).json()["favorite"] is False
    assert works(client)["favoriteCount"] == 0


def test_edits_survive_restart(settings: Settings) -> None:
    seed_library(settings, 10)
    with client_for(settings) as client:
        client.patch(
            "/api/v1/works/syn-multipart/personal",
            json={"rating": 4, "note": "重启后还在", "status": "paused", "favorite": True},
            headers=write_headers(client),
        )
    with client_for(settings) as client:
        detail = client.get("/api/v1/works/syn-multipart").json()
    assert (detail["rating"], detail["note"], detail["status"], detail["favorite"]) == (
        4,
        "重启后还在",
        "paused",
        True,
    )


# --- source metadata and personal records stay apart ---


def test_metadata_refresh_never_touches_personal_records(settings: Settings) -> None:
    seed_library(settings, 5)
    with client_for(settings) as client:
        client.patch(
            "/api/v1/works/syn-multipart/personal",
            json={"rating": 5, "note": "我的备注", "status": "completed", "favorite": True},
            headers=write_headers(client),
        )
    opened = open_database(settings.database_path, settings.backup_dir, "test")
    refreshed = SourceMetadata(
        source_id="dlsite", source_work_id="RJ900001", kind="game", title="多文件样本：新标题"
    )
    with opened.engine.begin() as connection:
        identifier = upsert_source_metadata(connection, refreshed)
        set_visibility(connection, "syn-hidden", "hidden")
    opened.engine.dispose()
    assert identifier == "syn-multipart"
    with client_for(settings) as client:
        detail = client.get("/api/v1/works/syn-multipart").json()
        assert detail["title"] == "多文件样本：新标题"
        assert works(client, search="新标题")["filteredCount"] == 1
    assert (detail["rating"], detail["note"], detail["status"], detail["favorite"]) == (
        5,
        "我的备注",
        "completed",
        True,
    )


def test_metadata_refresh_cannot_unhide_a_private_work(settings: Settings) -> None:
    seed_library(settings, 5)
    opened = open_database(settings.database_path, settings.backup_dir, "test")
    with opened.engine.begin() as connection:
        upsert_source_metadata(
            connection,
            SourceMetadata(
                source_id="steam", source_work_id="SENTINEL-private", title="公开新标题"
            ),
        )
    opened.engine.dispose()
    with client_for(settings) as client:
        assert client.get("/api/v1/works/syn-private").status_code == 404
        assert works(client, search="公开新标题")["filteredCount"] == 0


def test_new_work_starts_quarantined(settings: Settings) -> None:
    seed_library(settings, 6)
    opened = open_database(settings.database_path, settings.backup_dir, "test")
    with opened.engine.begin() as connection:
        identifier = upsert_source_metadata(
            connection, SourceMetadata(source_id="dlsite", source_work_id="RJ1", title="新条目")
        )
    opened.engine.dispose()
    with client_for(settings) as client:
        assert client.get(f"/api/v1/works/{identifier}").status_code == 404
        assert works(client)["totalVisible"] == 6


def test_failed_transaction_leaves_nothing_behind(settings: Settings) -> None:
    seed_library(settings, 1)
    opened = open_database(settings.database_path, settings.backup_dir, "test")
    with pytest.raises(IntegrityError), opened.engine.begin() as connection:
        identifier = upsert_source_metadata(
            connection, SourceMetadata(source_id="dlsite", source_work_id="RJ2", title="半条")
        )
        replace_work_files(connection, identifier, [WorkFile(availability="bogus")])
    opened.engine.dispose()
    with client_for(settings) as client:
        assert works(client, search="半条")["filteredCount"] == 0
    opened = open_database(settings.database_path, settings.backup_dir, "test")
    with opened.engine.connect() as connection:
        assert (
            connection.exec_driver_sql(
                "SELECT count(*) FROM works WHERE source_work_id = 'RJ2'"
            ).scalar()
            == 0
        )
    opened.engine.dispose()


# --- dashboard ---


def test_dashboard_counts_match_the_library(client: TestClient) -> None:
    items = all_items(client)
    for scope, filters in (
        ("all", {}),
        ("games", {"kind": "game"}),
        ("steam", {"platform": "steam"}),
        ("dlsite-games", {"platform": "dlsite", "kind": "game"}),
        ("dlsite-media", {"platform": "dlsite", "kind": "non-game"}),
    ):
        data = client.get("/api/v1/dashboard", params={"scope": scope}).json()
        assert data["totals"]["works"] == works(client, **filters)["filteredCount"], scope
        assert data["hasGames"] is (scope != "dlsite-media")
    data = client.get("/api/v1/dashboard").json()
    games = [item for item in items if item["kind"] == "game"]
    played = [item for item in games if (item["playtimeMinutes"] or 0) > 0]
    assert data["totals"]["games"] == len(games)
    assert data["totals"]["playedGames"] == len(played)
    assert data["totals"]["unknownPlaytimeGames"] == sum(
        item["playtimeMinutes"] is None for item in games
    )
    assert data["totals"]["playtimeMinutes"] == sum(item["playtimeMinutes"] or 0 for item in games)
    assert sum(bucket["count"] for bucket in data["playtimeBuckets"]) == len(played)
    assert sum(row["count"] for row in data["genres"]) == len(games)
    kinds = Counter(item["kind"] for item in items)
    assert {row["kind"]: row["steam"] + row["dlsite"] for row in data["kinds"]} == {
        kind: kinds[kind] for kind in ("game", "image", "video", "audio", "other")
    }


def test_dashboard_never_invents_play_data_for_other_kinds(client: TestClient) -> None:
    data = client.get("/api/v1/dashboard", params={"scope": "dlsite-media"}).json()
    assert data["hasGames"] is False
    assert data["totals"]["games"] == 0
    assert data["totals"]["playtimeMinutes"] == 0
    assert data["mostPlayed"] == []
    assert sum(bucket["count"] for bucket in data["playtimeBuckets"]) == 0


def test_recommendations_are_stable_within_a_batch(client: TestClient) -> None:
    first = client.get("/api/v1/dashboard", params={"batch": 1}).json()["recommendations"]
    again = client.get("/api/v1/dashboard", params={"batch": 1}).json()["recommendations"]
    other = client.get("/api/v1/dashboard", params={"batch": 2}).json()["recommendations"]
    assert first == again
    assert 0 < len(first) <= 3
    assert all(item["game"]["status"] in ("unplayed", "paused") for item in first)
    assert [item["game"]["id"] for item in first] != [item["game"]["id"] for item in other]


def test_dashboard_on_empty_library(empty_client: TestClient) -> None:
    data = empty_client.get("/api/v1/dashboard").json()
    assert data["totals"]["works"] == 0
    assert data["featured"] == []
    assert data["recommendations"] == []


# --- privacy ---


def test_private_works_appear_nowhere(client: TestClient, writer: dict) -> None:
    assert len(build_samples(120)) == 123
    responses = [
        client.get("/api/v1/works", params={"limit": 100, "offset": offset})
        for offset in range(0, 200, 100)
    ]
    responses += [client.get("/api/v1/works", params={"search": "SENTINEL"})]
    responses += [client.get("/api/v1/works", params={"genre": "SENTINEL-GENRE"})]
    for scope in ("all", "games", "steam", "dlsite-games", "dlsite-media"):
        responses.append(client.get("/api/v1/dashboard", params={"scope": scope}))
    responses.append(client.get("/api/v1/sources"))
    for response in responses:
        assert response.status_code == 200
        assert SENTINEL_MARK not in response.text
        for identifier in SENTINEL_IDS:
            assert identifier not in response.text
    page = works(client)
    assert page["totalVisible"] == 120
    assert "SENTINEL-GENRE" not in page["genres"]
    assert works(client, search="SENTINEL")["filteredCount"] == 0
    sources = client.get("/api/v1/sources").json()["sources"]
    assert sum(source["workCount"] for source in sources) == 120


def test_private_and_absent_ids_are_indistinguishable(client: TestClient, writer: dict) -> None:
    def shape(response) -> tuple:
        body = response.json()
        body["error"].pop("requestId")
        return response.status_code, json.dumps(body, sort_keys=True)

    for request in (
        lambda work_id: client.get(f"/api/v1/works/{work_id}"),
        lambda work_id: client.patch(
            f"/api/v1/works/{work_id}/personal", json={"note": "x"}, headers=writer
        ),
        lambda work_id: client.patch(
            f"/api/v1/works/{work_id}/personal",
            json={"note": "x", "expectedVersion": 99},
            headers=writer,
        ),
        lambda work_id: client.post(f"/api/v1/works/{work_id}/favorite/toggle", headers=writer),
    ):
        absent = shape(request("no-such-work"))
        assert absent[0] == 404
        for identifier in SENTINEL_IDS:
            assert shape(request(identifier)) == absent


def test_edits_never_reach_private_works(settings: Settings) -> None:
    seed_library(settings, 3)
    with client_for(settings) as client:
        client.patch(
            "/api/v1/works/syn-private/personal",
            json={"note": "不应写入"},
            headers=write_headers(client),
        )
    opened = open_database(settings.database_path, settings.backup_dir, "test")
    with opened.engine.connect() as connection:
        note = connection.exec_driver_sql(
            "SELECT note FROM personal_records WHERE work_id = 'syn-private'"
        ).scalar()
    opened.engine.dispose()
    assert note == ""


@pytest.mark.parametrize(
    "params",
    [{"includePrivate": "true"}, {"visibility": "private"}, {"scope": "private"}, {"limit": 500}],
)
def test_no_query_parameter_widens_the_scope(client: TestClient, params: dict) -> None:
    response = client.get("/api/v1/works", params=params)
    assert response.status_code == 422
    assert SENTINEL_MARK not in response.text


def test_invalid_list_parameters_are_refused(client: TestClient) -> None:
    for params in ({"kind": "bogus"}, {"sort": "bogus"}, {"offset": -1}, {"limit": 0}):
        assert client.get("/api/v1/works", params=params).status_code == 422
    assert client.get("/api/v1/dashboard", params={"scope": "private"}).status_code == 422


# --- local request boundary ---


def test_write_needs_origin_and_token(client: TestClient, writer: dict) -> None:
    url = "/api/v1/works/syn-multipart/personal"
    body = {"note": "x"}
    missing_token = client.patch(url, json=body, headers={"Origin": writer["Origin"]})
    assert missing_token.status_code == 403
    assert missing_token.json()["error"]["code"] == "csrf_invalid"
    wrong_token = client.patch(
        url, json=body, headers={"Origin": writer["Origin"], "X-Atlas-CSRF": "guess"}
    )
    assert wrong_token.status_code == 403
    no_origin = client.patch(url, json=body, headers={"X-Atlas-CSRF": writer["X-Atlas-CSRF"]})
    assert no_origin.status_code == 403
    assert no_origin.json()["error"]["code"] == "origin_required"
    assert client.get("/api/v1/works/syn-multipart").json()["version"] == 1
    assert client.patch(url, json=body, headers=writer).status_code == 200


@pytest.mark.parametrize(
    "origin",
    ["https://evil.example", "http://127.0.0.1.evil.example", "null", "http://127.0.0.1:1"],
)
def test_other_origins_are_refused(client: TestClient, writer: dict, origin: str) -> None:
    read = client.get("/api/v1/works", headers={"Origin": origin})
    assert read.status_code == 403
    assert "syn-" not in read.text
    assert read.headers.get("access-control-allow-origin") is None
    assert client.get("/api/v1/session", headers={"Origin": origin}).status_code == 403
    write = client.patch(
        "/api/v1/works/syn-multipart/personal",
        json={"note": "x"},
        headers={"Origin": origin, "X-Atlas-CSRF": writer["X-Atlas-CSRF"]},
    )
    assert write.status_code == 403


def test_cross_site_fetch_metadata_is_refused(client: TestClient) -> None:
    for path in ("/api/v1/works", "/api/v1/session"):
        assert client.get(path, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get("/api/v1/works", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200


@pytest.mark.parametrize(
    "host", ["evil.example", "evil.example:8765", "127.0.0.1:9999", "0.0.0.0:8765"]
)
def test_dns_rebinding_hosts_are_refused(client: TestClient, host: str) -> None:
    response = client.get("/api/v1/works", headers={"Host": host})
    assert response.status_code == 421
    assert "syn-" not in response.text


def test_token_changes_with_every_start(settings: Settings) -> None:
    seed_library(settings, 3)
    with client_for(settings) as first:
        old = write_headers(first)
    with client_for(settings) as second:
        response = second.patch(
            "/api/v1/works/syn-multipart/personal", json={"note": "x"}, headers=old
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "csrf_invalid"


def test_no_cors_headers_are_ever_sent(client: TestClient) -> None:
    preflight = client.options(
        "/api/v1/works/syn-multipart/personal",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "PATCH"},
    )
    assert preflight.status_code == 403
    assert "access-control-allow-origin" not in preflight.headers


def test_errors_and_logs_do_not_leak(settings: Settings, caplog: pytest.LogCaptureFixture) -> None:
    seed_library(settings, 3)
    secret_search = "私人搜索词XYZ"
    with caplog.at_level("INFO", logger="atlas"), client_for(settings) as client:
        client.get("/api/v1/works", params={"search": secret_search})
        client.get("/api/v1/works/syn-private")
        client.patch(
            "/api/v1/works/syn-multipart/personal",
            json={"note": "私人备注XYZ"},
            headers=write_headers(client),
        )
    logged = caplog.text
    assert "/api/v1/works/{work_id}" in logged
    for leak in (secret_search, "syn-private", "私人备注XYZ", str(settings.data_dir)):
        assert leak not in logged


def test_static_and_api_share_the_security_headers(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-request-id"]


@pytest.mark.parametrize(
    ("sort", "field", "descending"),
    [
        ("maker-asc", "maker", False),
        ("maker-desc", "maker", True),
        ("genre-asc", "genre", False),
        ("genre-desc", "genre", True),
        ("release-desc", "releaseDate", True),
        ("release-asc", "releaseDate", False),
        ("added-desc", "addedAt", True),
        ("added-asc", "addedAt", False),
    ],
)
def test_column_sorts_order_and_keep_unknowns_last(
    client: TestClient, sort: str, field: str, descending: bool
) -> None:
    values = [item[field] for item in all_items(client, sort=sort)]
    known = [value for value in values if value is not None]
    assert values == known + [None] * (len(values) - len(known))
    assert known == sorted(known, reverse=descending)


def test_rating_sort_follows_personal_records(client: TestClient, writer: dict) -> None:
    for work_id, rating in (("syn-multipart", 2), ("syn-unknown", 5)):
        client.patch(f"/api/v1/works/{work_id}/personal", json={"rating": rating}, headers=writer)
    high = all_items(client, sort="rating-desc")
    assert [i["id"] for i in high[:2]] == ["syn-unknown", "syn-multipart"]
    assert high[0]["rating"] == 5
    low = all_items(client, sort="rating-asc")
    assert [i["id"] for i in low[:2]] == ["syn-multipart", "syn-unknown"]
    assert low[-1]["rating"] is None
