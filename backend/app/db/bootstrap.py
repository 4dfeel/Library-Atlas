"""Opens a library database: version check, backup, migration, profile stamp."""

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, select
from sqlalchemy.exc import DatabaseError

from app.core.config import Profile
from app.db.engine import make_engine
from app.db.schema import library_meta

MIGRATIONS = Path(__file__).parent / "migrations"
KEEP_BACKUPS = 5


class DatabaseNotReady(Exception):
    """A stable reason; the display text lives in NOT_READY_MESSAGES."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class OpenedDatabase:
    engine: Engine
    revision: str
    backup: Path | None


def _config(extra_versions: tuple[Path, ...]) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS).replace("%", "%%"))
    if extra_versions:
        locations = (MIGRATIONS / "versions", *extra_versions)
        config.set_main_option("path_separator", ";")
        config.set_main_option(
            "version_locations", ";".join(str(path).replace("%", "%%") for path in locations)
        )
    return config


def backup_database(database: Path, backup_dir: Path, label: str) -> Path:
    """Online backup through SQLite, verified before it counts. Old copies are pruned."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    target = backup_dir / f"library-{stamp}-{label}.sqlite3"
    source = sqlite3.connect(database)
    try:
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()
        finally:
            destination.close()
    finally:
        source.close()
    if not result or result[0] != "ok":
        target.unlink(missing_ok=True)
        raise DatabaseNotReady("backup_failed")
    for old in sorted(backup_dir.glob("library-*.sqlite3"))[:-KEEP_BACKUPS]:
        old.unlink()
    return target


def open_database(
    database: Path,
    backup_dir: Path,
    profile: Profile,
    *,
    extra_versions: tuple[Path, ...] = (),
) -> OpenedDatabase:
    existed = database.exists() and database.stat().st_size > 0
    engine = make_engine(database)
    config = _config(extra_versions)
    scripts = ScriptDirectory.from_config(config)
    head = scripts.get_current_head()
    if head is None:
        raise DatabaseNotReady("migrations_missing")
    known = {script.revision for script in scripts.walk_revisions()}
    backup: Path | None = None
    try:
        with engine.connect() as connection:
            if existed and connection.exec_driver_sql("PRAGMA quick_check").scalar() != "ok":
                raise DatabaseNotReady("database_corrupt")
            current = MigrationContext.configure(connection).get_current_revision()
        if current is not None and current not in known:
            raise DatabaseNotReady("schema_too_new")
        if current != head:
            if existed and current is not None:
                backup = backup_database(database, backup_dir, f"before-{head}")
            with engine.begin() as connection:
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
        with engine.begin() as connection:
            stored = connection.execute(
                select(library_meta.c.value).where(library_meta.c.key == "profile")
            ).scalar()
            if stored is None:
                connection.execute(
                    library_meta.insert(),
                    [
                        {"key": "profile", "value": profile},
                        {"key": "library_id", "value": uuid.uuid4().hex},
                        {"key": "created_at", "value": datetime.now(UTC).isoformat()},
                    ],
                )
            elif stored != profile:
                raise DatabaseNotReady("profile_mismatch")
    except DatabaseNotReady:
        engine.dispose()
        raise
    except DatabaseError:
        engine.dispose()
        # Never replace or touch the file: it may hold the user's only copy.
        raise DatabaseNotReady("database_corrupt" if existed else "database_unavailable") from None
    except Exception:
        engine.dispose()
        raise DatabaseNotReady("migration_failed") from None
    return OpenedDatabase(engine=engine, revision=head, backup=backup)
