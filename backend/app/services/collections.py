"""The user's own named collections of works.

Taking a work out, or removing a collection, touches nothing else. Counts and membership go through
the ordinary scope, so a hidden work does not show, even as a number, and comes back when it is
visible again.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, Row, delete, func, select, update
from sqlalchemy.dialects.sqlite import insert

from app.api import models
from app.core.errors import AtlasError
from app.db.engine import writing
from app.db.schema import collection_items, collections, personal_records, works
from app.repositories.works import ORDINARY, get_ordinary_work

_MAX_COLLECTIONS = 500


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Collections:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def listed(self, work_id: str | None = None) -> models.CollectionsOut:
        ordinary = (
            select(collection_items.c.collection_id, collection_items.c.work_id)
            .join(works, works.c.id == collection_items.c.work_id)
            .join(personal_records, personal_records.c.work_id == works.c.id)
            .where(ORDINARY)
            .subquery()
        )
        with self._engine.connect() as connection:
            if work_id is not None:
                get_ordinary_work(connection, work_id)
            rows = connection.execute(
                select(collections).order_by(collections.c.name_key, collections.c.id)
            ).all()
            counts = dict(
                connection.execute(
                    select(ordinary.c.collection_id, func.count()).group_by(
                        ordinary.c.collection_id
                    )
                )
                .tuples()
                .all()
            )
            holding = (
                set(
                    connection.execute(
                        select(collection_items.c.collection_id).where(
                            collection_items.c.work_id == work_id
                        )
                    ).scalars()
                )
                if work_id is not None
                else set()
            )
            favorites = connection.execute(
                select(func.count())
                .select_from(personal_records)
                .join(works, works.c.id == personal_records.c.work_id)
                .where(ORDINARY, personal_records.c.favorite == 1)
            ).scalar_one()
        return models.CollectionsOut(
            favorites=favorites,
            collections=[
                models.CollectionOut(
                    id=row.id,
                    name=row.name,
                    count=counts.get(row.id, 0),
                    contains=row.id in holding,
                )
                for row in rows
            ],
        )

    @staticmethod
    def _taken(existing: Row[Any] | None) -> None:
        if existing is not None:
            raise AtlasError("collection_exists", "已经有同名的收藏了。", status=409)

    def create(self, body: models.CollectionIn) -> models.CollectionsOut:
        name = body.name.strip()
        if not name:
            raise AtlasError("collection_invalid", "请填写名称。", status=422)
        collection_id = uuid.uuid4().hex
        with self._engine.connect() as connection:
            if body.work_id is not None:
                get_ordinary_work(connection, body.work_id)
        with writing(self._engine).begin() as connection:
            self._taken(
                connection.execute(
                    select(collections.c.id).where(collections.c.name_key == name.casefold())
                ).first()
            )
            if (
                connection.execute(select(func.count()).select_from(collections)).scalar_one()
                >= _MAX_COLLECTIONS
            ):
                raise AtlasError("collection_invalid", "收藏太多了。", status=422)
            connection.execute(
                collections.insert().values(
                    id=collection_id, name=name, name_key=name.casefold(), created_at=_now()
                )
            )
            if body.work_id is not None:
                connection.execute(
                    collection_items.insert().values(
                        collection_id=collection_id, work_id=body.work_id, added_at=_now()
                    )
                )
        return self.listed(body.work_id)

    def rename(self, collection_id: str, body: models.CollectionRename) -> models.CollectionsOut:
        name = body.name.strip()
        if not name:
            raise AtlasError("collection_invalid", "请填写名称。", status=422)
        with writing(self._engine).begin() as connection:
            self._taken(
                connection.execute(
                    select(collections.c.id).where(
                        collections.c.name_key == name.casefold(),
                        collections.c.id != collection_id,
                    )
                ).first()
            )
            changed = connection.execute(
                update(collections)
                .where(collections.c.id == collection_id)
                .values(name=name, name_key=name.casefold())
            ).rowcount
        if not changed:
            raise AtlasError("collection_not_found", "找不到这个收藏。", status=404)
        return self.listed()

    def remove(self, collection_id: str) -> models.CollectionsOut:
        """Only the collection. Its works stay in the library, with everything about them."""
        with writing(self._engine).begin() as connection:
            connection.execute(
                delete(collection_items).where(collection_items.c.collection_id == collection_id)
            )
            connection.execute(delete(collections).where(collections.c.id == collection_id))
        return self.listed()

    def add_work(self, collection_id: str, work_id: str) -> models.CollectionsOut:
        with self._engine.connect() as connection:
            get_ordinary_work(connection, work_id)
            if (
                connection.execute(
                    select(collections.c.id).where(collections.c.id == collection_id)
                ).first()
                is None
            ):
                raise AtlasError("collection_not_found", "找不到这个收藏。", status=404)
        with writing(self._engine).begin() as connection:
            connection.execute(
                insert(collection_items)
                .values(collection_id=collection_id, work_id=work_id, added_at=_now())
                .on_conflict_do_nothing()
            )
        return self.listed(work_id)

    def remove_work(self, collection_id: str, work_id: str) -> models.CollectionsOut:
        with self._engine.connect() as connection:
            get_ordinary_work(connection, work_id)
        with writing(self._engine).begin() as connection:
            connection.execute(
                delete(collection_items).where(
                    collection_items.c.collection_id == collection_id,
                    collection_items.c.work_id == work_id,
                )
            )
        return self.listed(work_id)
