"""Tests use a real SQLite file in a temporary directory and the real app; nothing is mocked."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import TEST_MARKER, Settings
from app.db.bootstrap import open_database
from app.main import create_app
from app.testing import synthetic

ORIGIN = "http://127.0.0.1:8765"


def make_settings(data_dir: Path) -> Settings:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / TEST_MARKER).write_text("test", encoding="utf-8")
    return Settings(profile="test", data_dir=data_dir, port=8765, static_dir=None)


def client_for(settings: Settings) -> TestClient:
    return TestClient(create_app(settings), base_url=ORIGIN, raise_server_exceptions=False)


def seed_library(settings: Settings, size: int = 120) -> None:
    opened = open_database(settings.database_path, settings.backup_dir, settings.profile)
    synthetic.seed(opened.engine, size)
    opened.engine.dispose()


def write_headers(client: TestClient) -> dict[str, str]:
    token = client.get("/api/v1/session").json()["csrfToken"]
    return {"Origin": ORIGIN, "X-Atlas-CSRF": token}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path / "数据 目录")


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    seed_library(settings)
    with client_for(settings) as test_client:
        yield test_client


@pytest.fixture
def empty_client(settings: Settings) -> Iterator[TestClient]:
    with client_for(settings) as test_client:
        yield test_client


@pytest.fixture
def writer(client: TestClient) -> dict[str, str]:
    return write_headers(client)


__all__ = ["ORIGIN", "client_for", "seed_library", "make_settings", "write_headers"]
