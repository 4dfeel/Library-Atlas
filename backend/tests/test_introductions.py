# ruff: noqa: E501 - made-up HTML reads better on one line.
"""The store introduction: what the parser lets through, and how a failed look behaves. Real API
and database; the pages are made up, and no real page is copied here."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.adapters.dlsite.library import PlatformUnavailable, ResponseChanged
from app.adapters.dlsite.store_page import PublicStorePage, StorePageGone, parse_introduction
from app.core.config import Settings
from app.db.schema import personal_records, works
from tests.conftest import client_for
from tests.test_downloads import Rig, engine_of, first_work, prepare

BASE = "https://www.dlsite.com/maniax/work/=/product_id/RJ1.html"


def page(inner: str) -> str:
    return f'<html><body><nav>导航</nav><div class="work_parts_container">{inner}</div><footer>页脚</footer></body></html>'


def blocks(inner: str) -> list[dict[str, Any]]:
    return parse_introduction(page(inner), BASE)


def text_of(result: list[dict[str, Any]]) -> str:
    return "".join(
        span["text"] for block in result if block["type"] == "paragraph" for span in block["spans"]
    )


# --- the parser ---


def test_order_and_kinds_are_kept() -> None:
    result = blocks(
        '<h3>第一节</h3><p>甲<br/>乙</p><img src="//img.dlsite.jp/a.jpg" alt="说明" width="560" height="420"/>'
        "<h3>第二节</h3><ul><li>一</li><li>二</li></ul><table><tr><td>键</td><td>值</td></tr></table><p>丙</p>"
    )
    assert [block["type"] for block in result] == [
        "heading",
        "paragraph",
        "image",
        "heading",
        "list",
        "table",
        "paragraph",
    ]
    assert result[1]["spans"][0]["text"] == "甲\n乙"
    assert result[2] == {
        "type": "image",
        "ref": "https://img.dlsite.jp/a.jpg",
        "alt": "说明",
        "width": 560,
        "height": 420,
    }
    assert result[4]["items"] == ["一", "二"]
    assert result[5]["rows"] == [["键", "值"]]


def test_the_real_shape_of_a_section_reads_properly() -> None:
    """The same nesting the store uses: heading, image inside a link, text with line breaks."""
    result = blocks(
        '<div class="work_parts type_image"><h3 class="work_parts_heading">标题</h3>'
        '<div class="work_parts_area type_visual"><div class="work_parts_multitype type_top">'
        '<div class="work_parts_multitype_item type_contents">'
        '<a href="//img.dlsite.jp/b.jpg" target="blank"><img src="//img.dlsite.jp/a.jpg" alt="x" title="y"/></a>'
        '</div><div class="work_parts_multitype_item type_text"><p>第一行<br />\n<br />第二行</p></div>'
        "</div></div></div>"
    )
    assert [block["type"] for block in result] == ["heading", "image", "paragraph"]
    assert "第一行" in result[2]["spans"][0]["text"]
    assert "第二行" in result[2]["spans"][0]["text"]


def test_nothing_outside_the_section_comes_along() -> None:
    assert "导航" not in text_of(blocks("<p>内容</p>"))
    assert "页脚" not in text_of(blocks("<p>内容</p>"))


@pytest.mark.parametrize(
    "hostile",
    [
        "<script>alert(1)</script>",
        "<style>body{display:none}</style>",
        "<form action='https://evil.example'><input name=a><button>买</button></form>",
        "<object data='x'></object><embed src='x'>",
        "<svg onload='alert(1)'><text>svg</text></svg>",
        "<template><p>藏</p></template>",
    ],
)
def test_active_content_is_dropped_with_its_insides(hostile: str) -> None:
    result = blocks(f"<p>前</p>{hostile}<p>后</p>")
    assert [block["type"] for block in result] == ["paragraph", "paragraph"]
    dumped = str(result)
    for word in ("alert", "display", "evil", "买", "svg", "藏"):
        assert word not in dumped


def test_attributes_never_survive() -> None:
    result = blocks(
        '<p onclick="alert(1)" style="color:red">文字</p>'
        '<img src="//img.dlsite.jp/a.jpg" onerror="alert(1)" style="x"/>'
    )
    dumped = str(result)
    assert "alert" not in dumped
    assert "color" not in dumped


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        "JAVASCRIPT:alert(1)",
        " javascript:alert(1)",
        "data:text/html,x",
        "file:///C:/Windows/win.ini",
        "http://www.dlsite.com/x",
        "https://evil.example/x",
        "https://dlsite.com.evil.example/x",
    ],
)
def test_unsafe_links_become_plain_text(href: str) -> None:
    result = blocks(f'<p><a href="{href}">链接</a></p>')
    assert result[0]["spans"] == [{"text": "链接"}]


def test_platform_links_stay_and_relative_ones_resolve() -> None:
    result = blocks('<p>看<a href="/maniax/work/=/product_id/RJ2.html">这个</a>吧</p>')
    spans = result[0]["spans"]
    assert spans[1] == {
        "text": "这个",
        "href": "https://www.dlsite.com/maniax/work/=/product_id/RJ2.html",
    }
    assert spans[0]["text"] == "看"


@pytest.mark.parametrize(
    "source",
    [
        "https://evil.example/a.jpg",
        "javascript:alert(1)",
        "file:///C:/a.jpg",
        "http://img.dlsite.jp/a.jpg",
    ],
)
def test_images_only_from_platform_hosts(source: str) -> None:
    assert blocks(f'<img src="{source}"/>') == []


def test_videos_become_cards_and_other_frames_vanish() -> None:
    result = blocks(
        '<iframe src="https://chobit.cc/embed/x"></iframe>'
        '<iframe src="https://evil.example/x"></iframe><p>后</p>'
    )
    assert [block["type"] for block in result] == ["video", "paragraph"]
    assert "embed" not in str(result[0])


@pytest.mark.parametrize(
    "other",
    ["<html><body>请完成验证</body></html>", "", "<html><body><p>别的页面</p></body></html>"],
)
def test_a_page_without_the_section_is_never_an_empty_introduction(other: str) -> None:
    with pytest.raises(ResponseChanged):
        parse_introduction(other, BASE)


def test_nesting_of_the_same_tag_stays_inside() -> None:
    result = blocks("<div><div><p>里</p></div></div><p>外</p>")
    assert text_of(result) == "里外"


def test_an_enormous_page_is_bounded() -> None:
    result = blocks("<p>字</p>" * 5000)
    assert len(result) <= 500


# --- fetching ---


def _store(routes: dict[str, httpx.Response]) -> PublicStorePage:
    def answer(request: httpx.Request) -> httpx.Response:
        return routes.get(str(request.url), httpx.Response(404))

    return PublicStorePage(transport=httpx.MockTransport(answer))


URL_HOME = "https://www.dlsite.com/home/work/=/product_id/RJ1.html"
URL_MANIAX = "https://www.dlsite.com/maniax/work/=/product_id/RJ1.html"


def test_a_move_to_the_same_work_in_another_section_is_followed() -> None:
    store = _store(
        {
            URL_HOME: httpx.Response(302, headers={"location": URL_MANIAX}),
            URL_MANIAX: httpx.Response(200, text="页面"),
        }
    )
    assert store.fetch("home", "RJ1") == "页面"


@pytest.mark.parametrize(
    "target",
    [
        "https://www.dlsite.com/home/",
        "https://www.dlsite.com/maniax/work/=/product_id/RJ2.html",
        "https://evil.example/RJ1.html",
        "http://www.dlsite.com/maniax/work/=/product_id/RJ1.html",
    ],
)
def test_a_move_anywhere_else_means_no_page(target: str) -> None:
    store = _store({URL_HOME: httpx.Response(302, headers={"location": target})})
    with pytest.raises(StorePageGone):
        store.fetch("home", "RJ1")


def test_a_redirect_loop_ends() -> None:
    store = _store({URL_HOME: httpx.Response(302, headers={"location": URL_HOME})})
    with pytest.raises(StorePageGone):
        store.fetch("home", "RJ1")


def test_server_trouble_is_not_mistaken_for_a_missing_work() -> None:
    store = _store({URL_HOME: httpx.Response(503)})
    with pytest.raises(PlatformUnavailable):
        store.fetch("home", "RJ1")


# --- the service ---


@pytest.fixture
def rig(settings: Settings, tmp_path: Path) -> Rig:
    return Rig(settings, tmp_path)


@pytest.fixture
def api(settings: Settings, rig: Rig) -> Iterator[TestClient]:
    with client_for(settings) as client:
        prepare(client, rig)
        yield client


def intro(client: TestClient, work_id: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/works/{work_id}/introduction")
    assert response.status_code == 200
    result: dict[str, Any] = response.json()
    return result


def behave(rig: Rig, value: str | None) -> None:
    rig.control["intro"] = value
    rig.save_control()


def expire(client: TestClient, work_id: str) -> None:
    with engine_of(client).begin() as connection:
        connection.execute(update(works).where(works.c.id == work_id).values(intro_fetched_at=None))


def test_opening_a_work_reads_its_introduction(api: TestClient) -> None:
    data = intro(api, first_work(api)["id"])
    assert data["status"] == "ok"
    kinds = [block["type"] for block in data["blocks"]]
    assert {"heading", "paragraph", "image", "list", "table", "video"} <= set(kinds)
    assert data["fetchedAt"]
    assert data["stale"] is False


def test_images_go_through_atlas_by_position(api: TestClient) -> None:
    work = first_work(api)
    data = intro(api, work["id"])
    image = next(block for block in data["blocks"] if block["type"] == "image")
    assert image["url"] == f"/api/v1/works/{work['id']}/intro-image/0"
    assert "ref" not in image
    assert "dlsite" not in str([b for b in data["blocks"] if b["type"] == "image"])
    fetched = api.get(image["url"])
    assert fetched.status_code == 200
    assert fetched.content.startswith(b"\x89PNG")
    assert api.get(f"/api/v1/works/{work['id']}/intro-image/99").status_code == 404


def test_the_answer_is_kept_and_not_read_twice(api: TestClient, rig: Rig) -> None:
    work = first_work(api)
    assert intro(api, work["id"])["status"] == "ok"
    behave(rig, "offline")
    again = intro(api, work["id"])
    assert again["status"] == "ok"
    assert again["stale"] is False  # It did not even ask.


@pytest.mark.parametrize(
    ("mode", "problem"),
    [("offline", "unavailable"), ("changed", "changed"), ("gone", "gone")],
)
def test_a_failed_look_loses_nothing(api: TestClient, rig: Rig, mode: str, problem: str) -> None:
    work = first_work(api)
    first = intro(api, work["id"])
    behave(rig, mode)
    expire(api, work["id"])
    after = intro(api, work["id"])
    assert after["status"] == "ok"
    assert after["stale"] is True
    assert after["problem"] == problem
    assert after["message"]
    assert after["blocks"] == first["blocks"]


@pytest.mark.parametrize("mode", ["offline", "changed", "gone"])
def test_a_failed_first_look_is_not_stored_as_empty(api: TestClient, rig: Rig, mode: str) -> None:
    behave(rig, mode)
    work = first_work(api)
    data = intro(api, work["id"])
    assert data["status"] == "unavailable"
    assert data["blocks"] == []
    behave(rig, None)
    assert intro(api, work["id"])["status"] == "ok"  # It looks again next time.


def test_a_page_with_no_introduction_is_truly_empty(api: TestClient, rig: Rig) -> None:
    behave(rig, "none")
    data = intro(api, first_work(api)["id"])
    assert data["status"] == "empty"
    assert data["problem"] is None


def test_refresh_is_explicit_and_not_a_flood(api: TestClient, rig: Rig) -> None:
    work = first_work(api)
    intro(api, work["id"])
    behave(rig, "offline")
    url = f"/api/v1/works/{work['id']}/introduction/refresh"
    assert api.post(url).json()["stale"] is False  # Just read: a second look is not worth it.
    with engine_of(api).begin() as connection:
        connection.execute(
            update(works)
            .where(works.c.id == work["id"])
            .values(intro_fetched_at="2020-01-01T00:00:00+00:00")
        )
    assert api.post(url).json()["stale"] is True


def test_personal_records_are_untouched(api: TestClient) -> None:
    work = first_work(api)
    detail = api.get(f"/api/v1/works/{work['id']}").json()
    api.patch(
        f"/api/v1/works/{work['id']}/personal",
        json={"note": "我的备注", "expectedVersion": detail["version"]},
    )
    intro(api, work["id"])
    after = api.get(f"/api/v1/works/{work['id']}").json()
    assert after["note"] == "我的备注"


@pytest.mark.parametrize("visibility", ["hidden", "private", "quarantined"])
def test_works_outside_ordinary_views_get_nothing(api: TestClient, visibility: str) -> None:
    work = first_work(api)
    intro(api, work["id"])
    with engine_of(api).begin() as connection:
        connection.execute(
            update(personal_records)
            .where(personal_records.c.work_id == work["id"])
            .values(visibility=visibility)
        )
    assert api.get(f"/api/v1/works/{work['id']}/introduction").status_code == 404
    assert api.get(f"/api/v1/works/{work['id']}/intro-image/0").status_code == 404


def test_browsing_the_library_reads_no_store_pages(api: TestClient) -> None:
    api.get("/api/v1/works", params={"limit": 100})
    api.get("/api/v1/dashboard", params={"scope": "all"})
    with engine_of(api).connect() as connection:
        rows = connection.execute(
            update(works)
            .values(metadata_updated_at=works.c.metadata_updated_at)
            .returning(works.c.intro_fetched_at)
        ).all()
    assert all(row[0] is None for row in rows)


def test_other_platforms_ask_nothing(api: TestClient) -> None:
    work = first_work(api)
    with engine_of(api).begin() as connection:
        connection.execute(update(works).where(works.c.id == work["id"]).values(source_id="steam"))
    assert intro(api, work["id"]) == {
        "status": "empty",
        "blocks": [],
        "fetchedAt": None,
        "stale": False,
        "problem": None,
        "message": None,
    }
