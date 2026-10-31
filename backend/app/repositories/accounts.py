"""The DLsite account row: non-secret state only. One library has one account per source;
a different account gets its own confirmation, and its own profile directory later."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, Row, select
from sqlalchemy.dialects.sqlite import insert

from app.db.schema import library_meta, source_accounts

DLSITE_ACCOUNT_ID = "dlsite-default"


def library_id(connection: Connection) -> str:
    return str(
        connection.execute(
            select(library_meta.c.value).where(library_meta.c.key == "library_id")
        ).scalar_one()
    )


def get_account(connection: Connection) -> Row[Any] | None:
    return connection.execute(
        select(source_accounts).where(source_accounts.c.id == DLSITE_ACCOUNT_ID)
    ).first()


def _upsert(connection: Connection, **values: Any) -> None:
    connection.execute(
        insert(source_accounts)
        .values(id=DLSITE_ACCOUNT_ID, source_id="dlsite", **values)
        .on_conflict_do_update(index_elements=[source_accounts.c.id], set_=values)
    )


def save_connected(
    connection: Connection,
    *,
    credential_ref: str,
    fingerprint: str | None,
    alias: str | None,
    verified: bool,
) -> None:
    values: dict[str, Any] = {
        "credential_ref": credential_ref,
        "state": "connected",
        "cleanup_pending": 0,
        "account_alias": alias,
    }
    if fingerprint is not None:
        values["account_fingerprint"] = fingerprint
    if verified:
        values["last_verified_at"] = datetime.now(UTC).isoformat()
    _upsert(connection, **values)


def mark_verified(connection: Connection) -> None:
    _upsert(connection, state="connected", last_verified_at=datetime.now(UTC).isoformat())


def set_state(connection: Connection, state: str) -> None:
    _upsert(connection, state=state)


def disable(connection: Connection) -> None:
    """Committed before cleanup starts: after this, a restart never restores the session."""
    _upsert(connection, state="not_connected", cleanup_pending=1, last_verified_at=None)


def cleanup_done(connection: Connection) -> None:
    _upsert(connection, cleanup_pending=0, credential_ref=None)
