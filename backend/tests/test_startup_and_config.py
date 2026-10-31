import socket
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app.__main__ import EXIT_CONFIG, EXIT_DATABASE, EXIT_PORT, main
from app.core.config import TEST_MARKER, ConfigError, Settings, load_settings
from app.core.credentials import CredentialTooLarge, WindowsCredentialStore
from app.main import _static_response
from tests.conftest import HEAD_REVISION, client_for, make_settings, seed_library


def env_for(tmp_path: Path, **extra: str) -> dict[str, str]:
    return {"LOCALAPPDATA": str(tmp_path / "local"), **extra}


def test_default_path_is_created_and_independent_of_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    settings = load_settings(env_for(tmp_path))
    assert settings.data_dir == tmp_path / "local" / "LibraryAtlas" / "profiles" / "default"
    assert settings.data_dir.is_dir()
    assert settings.profile == "real"


def test_explicit_missing_directory_is_refused_not_created(tmp_path: Path) -> None:
    missing = tmp_path / "unplugged-drive"
    with pytest.raises(ConfigError, match="不存在"):
        load_settings(env_for(tmp_path, ATLAS_DATA_DIR=str(missing)))
    assert not missing.exists()


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"ATLAS_DATA_DIR": "relative/dir"}, "绝对路径"),
        ({"ATLAS_PROFILE": "other"}, "real 或 test"),
        ({"ATLAS_PORT": "80"}, "1024"),
        ({"ATLAS_PORT": "abc"}, "1024"),
        ({"ATLAS_DEV_ORIGINS": "https://evil.example"}, "回环"),
        ({"ATLAS_DEV_ORIGINS": "http://192.168.1.2:5173"}, "回环"),
    ],
)
def test_invalid_configuration_is_rejected(
    tmp_path: Path, extra: dict[str, str], message: str
) -> None:
    with pytest.raises(ConfigError, match=message):
        load_settings(env_for(tmp_path, **extra))


def test_data_dir_that_is_a_file_is_rejected(tmp_path: Path) -> None:
    file = tmp_path / "a-file"
    file.write_text("x", encoding="utf-8")
    with pytest.raises(ConfigError, match="不是目录"):
        load_settings(env_for(tmp_path, ATLAS_DATA_DIR=str(file)))


def test_test_profile_is_isolated_from_real_data(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="显式指定"):
        load_settings(env_for(tmp_path, ATLAS_PROFILE="test"))
    inside = tmp_path / "local" / "LibraryAtlas" / "inside"
    inside.mkdir(parents=True)
    with pytest.raises(ConfigError, match="之内"):
        load_settings(env_for(tmp_path, ATLAS_PROFILE="test", ATLAS_DATA_DIR=str(inside)))
    unmarked = tmp_path / "unmarked"
    unmarked.mkdir()
    with pytest.raises(ConfigError, match="未标记"):
        load_settings(env_for(tmp_path, ATLAS_PROFILE="test", ATLAS_DATA_DIR=str(unmarked)))
    (unmarked / TEST_MARKER).write_text("x", encoding="utf-8")
    with pytest.raises(ConfigError, match="不能作为真实"):
        load_settings(env_for(tmp_path, ATLAS_DATA_DIR=str(unmarked)))


def test_fresh_directory_becomes_ready_and_empty(empty_client) -> None:
    ready = empty_client.get("/api/v1/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready", "profile": "test", "schemaRevision": HEAD_REVISION}
    page = empty_client.get("/api/v1/works").json()
    assert page["items"] == []
    assert page["totalVisible"] == 0
    sources = empty_client.get("/api/v1/sources").json()["sources"]
    assert [source["id"] for source in sources] == ["steam", "dlsite"]
    assert {source["connection"] for source in sources} == {"not_connected"}
    assert {s["id"]: s["capabilities"]["connect"] for s in sources} == {
        "steam": False,
        "dlsite": True,
    }


def test_repeated_start_does_not_seed_or_duplicate(settings: Settings) -> None:
    seed_library(settings, 30)
    for _ in range(3):
        with client_for(settings) as client:
            assert client.get("/api/v1/ready").status_code == 200
            assert client.get("/api/v1/works").json()["totalVisible"] == 30


def test_health_stays_up_while_not_ready_and_data_routes_refuse(settings: Settings) -> None:
    settings.database_path.write_bytes(b"this is not a sqlite database" * 100)
    before = settings.database_path.read_bytes()
    with client_for(settings) as client:
        assert client.get("/api/v1/health").status_code == 200
        ready = client.get("/api/v1/ready")
        assert ready.status_code == 503
        assert ready.json()["reason"] == "database_corrupt"
        works = client.get("/api/v1/works")
        assert works.status_code == 503
        assert works.json()["error"]["code"] == "service_not_ready"
    assert settings.database_path.read_bytes() == before


def test_database_lost_after_start_is_not_reported_as_empty(settings: Settings) -> None:
    seed_library(settings, 5)
    with client_for(settings) as client:
        engine = client.app.state.service.engine
        engine.dispose()
        with closing(sqlite3.connect(settings.database_path)) as raw:
            raw.execute("DROP TABLE personal_records")
            raw.commit()
        response = client.get("/api/v1/works")
        assert response.status_code == 503
        body = response.json()["error"]
        assert body["code"] == "database_unavailable"
        assert body["retryable"] is True
        assert "personal_records" not in response.text
        assert "sqlite" not in response.text.lower()


def test_port_conflict_exits_without_touching_the_holder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = tmp_path / "library"
    data.mkdir()
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen()
        port = holder.getsockname()[1]
        code = main(["serve", "--profile", "real", "--data-dir", str(data), "--port", str(port)])
        assert code == EXIT_PORT
        assert "已被占用" in capsys.readouterr().err
        holder.getsockname()  # Still open and owned by this test.


def test_cli_rejects_bad_config_and_database(tmp_path: Path) -> None:
    assert main(["check", "--data-dir", str(tmp_path / "missing")]) == EXIT_CONFIG
    data = tmp_path / "broken"
    data.mkdir()
    (data / "library.sqlite3").write_bytes(b"x" * 8192)
    assert main(["check", "--data-dir", str(data)]) == EXIT_DATABASE


def test_seed_refuses_unmarked_non_empty_directory(tmp_path: Path) -> None:
    data = tmp_path / "someone-elses"
    data.mkdir()
    keep = data / "keep.txt"
    keep.write_text("user file", encoding="utf-8")
    assert main(["seed-test", "--data-dir", str(data)]) == EXIT_CONFIG
    assert keep.read_text(encoding="utf-8") == "user file"
    assert not (data / "library.sqlite3").exists()


def test_seed_and_reset_only_touch_the_marked_directory(tmp_path: Path) -> None:
    data = tmp_path / "test-lib"
    assert main(["seed-test", "--data-dir", str(data), "--size", "20"]) == 0
    assert main(["seed-test", "--data-dir", str(data), "--size", "20"]) == EXIT_CONFIG
    extra = data / "other.txt"
    extra.write_text("left alone", encoding="utf-8")
    assert main(["seed-test", "--data-dir", str(data), "--size", "20", "--reset"]) == 0
    assert extra.exists()


def test_static_hosting_never_leaves_the_build(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<title>Atlas shell</title>", encoding="utf-8")
    (dist / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside", encoding="utf-8")
    settings = make_settings(tmp_path / "data")
    settings = Settings(
        profile="test", data_dir=settings.data_dir, port=settings.port, static_dir=dist
    )
    with client_for(settings) as client:
        assert "console.log" in client.get("/app.js").text
        assert "Atlas shell" in client.get("/library/some-id").text
        for attempt in ("/../secret.txt", "/..%2fsecret.txt", "/%2e%2e/secret.txt"):
            assert "outside" not in client.get(attempt).text
        missing = client.get("/api/v1/nope")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "not_found"
        assert (
            client.get("/api/v1/works/x/nope")
            .headers["content-type"]
            .startswith("application/json")
        )


@pytest.fixture
def paths_asked_about(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What reached Windows. A network path stops here, so no test ever opens a connection."""
    asked: list[str] = []
    real_resolve = Path.resolve
    real_is_file = Path.is_file

    def resolve(self: Path, strict: bool = False) -> Path:
        asked.append(str(self))
        return self if str(self).startswith("\\\\") else real_resolve(self, strict)

    def is_file(self: Path, *, follow_symlinks: bool = True) -> bool:
        asked.append(str(self))
        if str(self).startswith("\\\\"):
            return False
        return real_is_file(self, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "resolve", resolve)
    monkeypatch.setattr(Path, "is_file", is_file)
    return asked


@pytest.mark.parametrize(
    "address",
    [
        "\\\\attacker.example\\share\\x",
        "//attacker.example/share/x",
        "/\\attacker.example\\share",
        "\\\\?\\UNC\\attacker.example\\share",
        "\\\\.\\pipe\\x",
        "C:\\Windows\\win.ini",
        "C:/Windows/win.ini",
        "C:win.ini",
        "NUL",
        "index.html::$DATA",
        "x\x00y",
    ],
)
def test_an_address_outside_the_build_is_never_asked_about(
    tmp_path: Path, paths_asked_about: list[str], address: str
) -> None:
    # Merely asking Windows about \\host\share offers that host the user's Windows credentials.
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<title>Atlas shell</title>", encoding="utf-8")
    root = dist.resolve()
    paths_asked_about.clear()
    response = _static_response(dist, address)
    assert response.path == root / "index.html"  # type: ignore[attr-defined]
    assert not [asked for asked in paths_asked_about if not Path(asked).is_relative_to(root.parent)]


def test_a_web_page_cannot_send_the_service_to_a_network_path(
    tmp_path: Path, paths_asked_about: list[str]
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<title>Atlas shell</title>", encoding="utf-8")
    settings = make_settings(tmp_path / "data")
    settings = Settings(
        profile="test", data_dir=settings.data_dir, port=settings.port, static_dir=dist
    )
    with client_for(settings) as client:
        paths_asked_about.clear()
        answer = client.get(
            "/%5C%5Cattacker.example%5Cshare%5Cx",
            headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Dest": "image"},
        )
        assert "Atlas shell" in answer.text
    assert not [asked for asked in paths_asked_about if "attacker.example" in asked]


def test_files_in_folders_of_the_build_are_still_served(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    (dist / "assets" / "cmaps").mkdir(parents=True)
    (dist / "index.html").write_text("<title>Atlas shell</title>", encoding="utf-8")
    (dist / "assets" / "cmaps" / "Adobe-Japan1-UCS2.bcmap").write_bytes(b"map")
    response = _static_response(dist, "assets/cmaps/Adobe-Japan1-UCS2.bcmap")
    assert Path(response.path).name == "Adobe-Japan1-UCS2.bcmap"  # type: ignore[attr-defined]


@pytest.fixture
def credential_store():
    try:
        store = WindowsCredentialStore(namespace="LibraryAtlas/pytest/")
    except Exception:
        pytest.skip("Windows credential store not available")
    yield store
    store.delete("probe")


def test_credential_store_round_trip_with_fake_value(credential_store) -> None:
    assert credential_store.read("probe") is None
    credential_store.write("probe", b"not-a-real-secret")
    assert credential_store.read("probe") == b"not-a-real-secret"
    credential_store.delete("probe")
    assert credential_store.read("probe") is None
    credential_store.delete("probe")  # Deleting twice is not an error.


def test_credential_store_fails_rather_than_truncates(credential_store) -> None:
    with pytest.raises(CredentialTooLarge):
        credential_store.write("probe", b"x" * 2561)
    assert credential_store.read("probe") is None
