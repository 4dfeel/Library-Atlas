import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import select

from app.core.config import Settings
from app.db.bootstrap import KEEP_BACKUPS, DatabaseNotReady, backup_database, open_database
from app.db.schema import metadata, personal_records
from app.repositories.works import PersonalChanges, update_personal
from tests.conftest import HEAD_REVISION as HEAD
from tests.conftest import client_for, seed_library

NEXT = f"{int(HEAD) + 1:04d}"

MIGRATION_0002 = """
import sqlalchemy as sa
from alembic import op
revision = "{NEXT}"
down_revision = "{HEAD}"
branch_labels = None
depends_on = None
def upgrade():
    op.add_column("works", sa.Column("probe_column", sa.String(), nullable=True))
"""
FAILING_0002 = """
import sqlalchemy as sa
from alembic import op
revision = "{NEXT}"
down_revision = "{HEAD}"
branch_labels = None
depends_on = None
def upgrade():
    op.add_column("works", sa.Column("probe_column", sa.String(), nullable=True))
    op.execute("UPDATE personal_records SET note = 'overwritten'")
    raise RuntimeError("simulated failure")
"""


def extra_migration(tmp_path: Path, source: str) -> Path:
    folder = tmp_path / "versions-extra"
    folder.mkdir()
    text = source.replace("{NEXT}", NEXT).replace("{HEAD}", HEAD)
    (folder / f"{NEXT}_probe.py").write_text(text, encoding="utf-8")
    return folder


def edit_one(settings: Settings) -> None:
    opened = open_database(settings.database_path, settings.backup_dir, settings.profile)
    with opened.engine.begin() as connection:
        update_personal(
            connection,
            "syn-steam-1001",
            PersonalChanges(values={"note": "迁移前的备注", "rating": 4}),
        )
    opened.engine.dispose()


def read_personal(database: Path) -> tuple[str, int]:
    with closing(sqlite3.connect(database)) as connection:
        return connection.execute(
            "SELECT note, rating FROM personal_records WHERE work_id = 'syn-steam-1001'"
        ).fetchone()


def test_migration_matches_the_declared_schema(settings: Settings) -> None:
    opened = open_database(settings.database_path, settings.backup_dir, settings.profile)
    with opened.engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), metadata)
    opened.engine.dispose()
    assert differences == []


def test_fresh_database_needs_no_backup(settings: Settings) -> None:
    opened = open_database(settings.database_path, settings.backup_dir, settings.profile)
    opened.engine.dispose()
    assert opened.backup is None
    assert opened.revision == HEAD


def test_upgrade_backs_up_first_and_keeps_edits(settings: Settings, tmp_path: Path) -> None:
    seed_library(settings, 10)
    edit_one(settings)
    opened = open_database(
        settings.database_path,
        settings.backup_dir,
        settings.profile,
        extra_versions=(extra_migration(tmp_path, MIGRATION_0002),),
    )
    with opened.engine.connect() as connection:
        row = connection.execute(
            select(personal_records.c.note).where(personal_records.c.work_id == "syn-steam-1001")
        ).scalar_one()
        columns = [c[1] for c in connection.exec_driver_sql("PRAGMA table_info(works)")]
    opened.engine.dispose()
    assert row == "迁移前的备注"
    assert "probe_column" in columns
    assert opened.revision == NEXT
    # The backup is a real, restorable copy of the state before the upgrade.
    assert opened.backup is not None
    assert read_personal(opened.backup) == ("迁移前的备注", 4)
    with closing(sqlite3.connect(opened.backup)) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (HEAD,)


def test_failed_upgrade_rolls_back_entirely(settings: Settings, tmp_path: Path) -> None:
    seed_library(settings, 10)
    edit_one(settings)
    with pytest.raises(DatabaseNotReady) as error:
        open_database(
            settings.database_path,
            settings.backup_dir,
            settings.profile,
            extra_versions=(extra_migration(tmp_path, FAILING_0002),),
        )
    assert error.value.reason == "migration_failed"
    assert read_personal(settings.database_path) == ("迁移前的备注", 4)
    with closing(sqlite3.connect(settings.database_path)) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (HEAD,)
        columns = [c[1] for c in connection.execute("PRAGMA table_info(works)")]
    assert "probe_column" not in columns


def test_restoring_a_backup_brings_the_data_back(settings: Settings) -> None:
    seed_library(settings, 10)
    edit_one(settings)
    backup = backup_database(settings.database_path, settings.backup_dir, "manual")
    with closing(sqlite3.connect(settings.database_path)) as connection:
        connection.execute("UPDATE personal_records SET note = 'later change'")
        connection.commit()
    for suffix in ("-wal", "-shm"):
        Path(f"{settings.database_path}{suffix}").unlink(missing_ok=True)
    shutil.copyfile(backup, settings.database_path)
    with client_for(settings) as client:
        assert client.get("/api/v1/ready").status_code == 200
        assert client.get("/api/v1/works/syn-steam-1001").json()["note"] == "迁移前的备注"


def test_old_backups_are_pruned(settings: Settings) -> None:
    seed_library(settings, 1)
    for index in range(KEEP_BACKUPS + 2):
        backup_database(settings.database_path, settings.backup_dir, f"b{index}")
    assert len(list(settings.backup_dir.glob("library-*.sqlite3"))) == KEEP_BACKUPS


def test_newer_schema_is_refused_without_changes(settings: Settings) -> None:
    seed_library(settings, 3)
    with closing(sqlite3.connect(settings.database_path)) as connection:
        connection.execute("UPDATE alembic_version SET version_num = '9999'")
        connection.commit()
    with client_for(settings) as client:
        ready = client.get("/api/v1/ready")
        assert ready.status_code == 503
        assert ready.json()["reason"] == "schema_too_new"
        assert client.get("/api/v1/works").status_code == 503
    with closing(sqlite3.connect(settings.database_path)) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("9999",)
        assert connection.execute("SELECT count(*) FROM works").fetchone()[0] > 0


def test_test_database_cannot_open_as_real(settings: Settings) -> None:
    seed_library(settings, 3)
    with pytest.raises(DatabaseNotReady) as error:
        open_database(settings.database_path, settings.backup_dir, "real")
    assert error.value.reason == "profile_mismatch"


def test_database_constraints_stop_bad_writes(settings: Settings) -> None:
    seed_library(settings, 3)
    with closing(sqlite3.connect(settings.database_path)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        for statement in (
            "UPDATE personal_records SET rating = 6",
            "UPDATE personal_records SET status = 'bogus'",
            "UPDATE personal_records SET visibility = 'bogus'",
            "UPDATE personal_records SET note = printf('%.1001c', 'x')",
            "UPDATE works SET kind = 'bogus'",
            "UPDATE works SET playtime_minutes = -1",
            "INSERT INTO personal_records (work_id, updated_at) VALUES ('no-such-work', 'x')",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(statement)
