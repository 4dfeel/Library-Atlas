"""User settings that are not secrets. Secrets never come here; see core/credentials.py."""

from sqlalchemy import Connection, select
from sqlalchemy.dialects.sqlite import insert

from app.db.schema import app_settings


def get(connection: Connection, key: str) -> str | None:
    value = connection.execute(
        select(app_settings.c.value).where(app_settings.c.key == key)
    ).scalar()
    return str(value) if value is not None else None


def put(connection: Connection, key: str, value: str) -> None:
    connection.execute(
        insert(app_settings)
        .values(key=key, value=value)
        .on_conflict_do_update(index_elements=[app_settings.c.key], set_={"value": value})
    )
