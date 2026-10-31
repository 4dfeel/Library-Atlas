"""SQLite engine with real transactions: every block starts with an explicit BEGIN, so
schema changes roll back too. Bound parameters are hidden from error messages."""

from pathlib import Path
from typing import Any

from sqlalchemy import URL, Connection, Engine, create_engine, event

_WRITES = "atlas_writes"


def make_engine(path: Path) -> Engine:
    engine = create_engine(
        URL.create("sqlite", database=str(path)),
        hide_parameters=True,
        connect_args={"check_same_thread": False, "timeout": 5},
    )

    @event.listens_for(engine, "connect")
    def _configure(connection: Any, _record: Any) -> None:
        connection.isolation_level = None
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    @event.listens_for(engine, "begin")
    def _begin(connection: Connection) -> None:
        immediate = connection.get_execution_options().get(_WRITES, False)
        connection.exec_driver_sql("BEGIN IMMEDIATE" if immediate else "BEGIN")

    return engine


def writing(engine: Engine) -> Engine:
    """For any transaction that writes. It takes the write lock up front, so it waits its
    turn. Started as a read, it could fail at once on reaching its first write if another
    thread had committed meanwhile, and waiting would not help: its snapshot is already old."""
    return engine.execution_options(**{_WRITES: True})
