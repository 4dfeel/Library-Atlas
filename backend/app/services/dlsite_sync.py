"""Reads the user's DLsite works into the library, when the user asks.

One job at a time, written in short transactions batch by batch, so a stop at any point
leaves whole works and running again is safe. A failed or partial run never removes works
or touches personal records. Each batch first checks the session is still the one the job
started with, so a logout or account change cannot let late answers into the library.
Requests are sequential and spaced; nothing here runs on a schedule.
"""

import logging
import threading
import time
import uuid
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import Engine, select, update

from app.adapters.dlsite.library import (
    LibraryClient,
    PlatformUnavailable,
    ResponseChanged,
    SessionRejected,
)
from app.adapters.dlsite.session import SessionCookie
from app.api import models
from app.db.schema import library_entries, source_accounts, sync_jobs, works
from app.domain.dlsite_works import map_work, owned_works
from app.repositories.accounts import DLSITE_ACCOUNT_ID
from app.repositories.works import upsert_source_metadata
from app.services.dlsite_auth import DlsiteAuth

logger = logging.getLogger("atlas")

BATCH_SIZE = 100  # The size the Play web app itself uses.
MAX_ATTEMPTS = 3
BATCH_PAUSE = 0.5
MAX_BATCHES = 2000  # A hard stop: no real library is 200,000 works.
MESSAGES = {
    "session_expired": "DLsite 登录已失效，请重新登录后再同步。已有作品不受影响。",
    "session_changed": "账号状态变了，这次同步已停止。已有作品不受影响。",
    "platform_unavailable": "暂时连不上 DLsite，这次同步没有完成。已有作品不受影响，可以重试。",
    "response_changed": "DLsite 返回的内容和预期不同，同步已停止，没有写入错误数据。",
    "some_unreadable": "有些作品的资料无法识别，已跳过。",
    "interrupted": "上次同步被中断了。已有作品不受影响，可以重新同步。",
    "cancelled": "同步已取消。已经读取的作品会保留。",
}
_ACTIVE = ("preparing", "reading", "saving")


class _Stop(Exception):
    def __init__(self, state: str, code: str | None) -> None:
        super().__init__(state)
        self.state = state
        self.code = code


def _now() -> str:
    return datetime.now(UTC).isoformat()


class DlsiteSync:
    def __init__(
        self,
        engine: Engine,
        auth: DlsiteAuth,
        client_factory: Callable[[list[SessionCookie]], LibraryClient],
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._engine = engine
        self._auth = auth
        self._client_factory = client_factory
        self._sleep = sleep
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None

    def recover(self) -> None:
        """A job still marked active after a restart was cut off. It is reported, not rerun."""
        with self._engine.begin() as connection:
            connection.execute(
                update(sync_jobs)
                .where(sync_jobs.c.state.in_(_ACTIVE))
                .values(state="interrupted", error_code="interrupted", finished_at=_now())
            )

    # --- reading ---

    def status(self) -> models.SyncStatus:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(sync_jobs).order_by(sync_jobs.c.started_at.desc()).limit(1)
            ).first()
            last = connection.execute(
                select(source_accounts.c.last_synced_at).where(
                    source_accounts.c.id == DLSITE_ACCOUNT_ID
                )
            ).scalar()
        if row is None:
            return models.SyncStatus(last_synced_at=last)
        return models.SyncStatus(
            last_synced_at=last,
            job=models.SyncJob(
                id=row.id,
                state=cast(models.SyncState, row.state),
                total=row.total,
                processed=row.processed,
                added=row.added,
                updated=row.updated,
                skipped=row.skipped,
                missing=row.missing,
                code=row.error_code,
                message=MESSAGES.get(row.error_code) if row.error_code else None,
                started_at=row.started_at,
                finished_at=row.finished_at,
            ),
        )

    # --- control ---

    def start(self) -> models.SyncStatus:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self.status()  # The same job, not a second one.
            cookies, generation = self._auth.session_for_sync()
            job_id = uuid.uuid4().hex
            with self._engine.begin() as connection:
                connection.execute(
                    sync_jobs.insert().values(id=job_id, state="preparing", started_at=_now())
                )
            self._cancel.clear()
            self._thread = threading.Thread(
                target=self._run,
                args=(job_id, cookies, generation),
                name="dlsite-sync",
                daemon=True,
            )
            self._thread.start()
        return self.status()

    def cancel(self) -> models.SyncStatus:
        self._cancel.set()
        return self.status()

    def shutdown(self) -> None:
        self._cancel.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5)

    # --- the job ---

    def _progress(self, job_id: str, **values: Any) -> None:
        with self._engine.begin() as connection:
            connection.execute(update(sync_jobs).where(sync_jobs.c.id == job_id).values(**values))

    def _check(self, generation: int) -> None:
        if self._cancel.is_set():
            raise _Stop("cancelled", "cancelled")
        if not self._auth.is_current(generation):
            raise _Stop("cancelled", "session_changed")

    def _call(self, generation: int, call: Callable[[], Any]) -> Any:
        """A few spaced tries for trouble that passes; a rejected session stops at once."""
        for attempt in range(MAX_ATTEMPTS):
            self._check(generation)
            try:
                return call()
            except SessionRejected:
                self._auth.session_rejected(generation)
                raise _Stop("reauth_required", "session_expired") from None
            except ResponseChanged:
                raise _Stop("failed", "response_changed") from None
            except PlatformUnavailable as error:
                if attempt == MAX_ATTEMPTS - 1:
                    raise _Stop("failed", "platform_unavailable") from None
                self._sleep(error.retry_after or 2.0 * (attempt + 1))
        raise AssertionError("unreachable")

    def _run(self, job_id: str, cookies: list[SessionCookie], generation: int) -> None:
        client: LibraryClient | None = None
        totals: Counter[str] = Counter()
        try:
            client = self._client_factory(cookies)
            self._execute(job_id, client, generation, totals)
        except _Stop as stop:
            state = stop.state
            # Works saved before a failure stay; the run is reported as partial, not clean.
            if state == "failed" and totals["processed"]:
                state = "partial"
            self._progress(job_id, state=state, error_code=stop.code, finished_at=_now())
        except Exception as error:  # noqa: BLE001 - must end the job; type only, no data.
            logger.error("sync failed: %s", type(error).__name__)
            self._progress(
                job_id, state="failed", error_code="response_changed", finished_at=_now()
            )
        finally:
            if client is not None:
                client.close()

    def _execute(
        self, job_id: str, client: LibraryClient, generation: int, totals: Counter[str]
    ) -> None:
        declared = self._call(generation, client.count)
        owned = owned_works(self._call(generation, client.owned))
        if owned is None or (declared > 0 and not owned):
            raise _Stop("failed", "response_changed")
        self._progress(job_id, state="reading", total=len(owned))
        batches = [owned[i : i + BATCH_SIZE] for i in range(0, len(owned), BATCH_SIZE)]
        if len(batches) > MAX_BATCHES:
            raise _Stop("failed", "response_changed")
        logged_fields = False
        kinds: Counter[str] = Counter()
        seen: set[str] = set()
        for index, batch in enumerate(batches):
            if index:
                self._sleep(BATCH_PAUSE)
            acquired = {item.source_work_id: item.acquired_at for item in batch}
            items = self._call(
                generation,
                lambda ids=list(acquired): client.works(ids),  # type: ignore[misc]
            )
            if not logged_fields and items and isinstance(items[0], dict):
                # Field names only, to spot a changed contract. Never any values.
                logger.info("sync fields: %s", ",".join(sorted(items[0])))
                logged_fields = True
            mapped = [map_work(item) for item in items]
            usable = [
                work for work in mapped if work is not None and work.source_work_id in acquired
            ]
            if items and not usable:
                raise _Stop("failed", "response_changed")
            self._check(generation)
            self._progress(job_id, state="saving")
            with self._engine.begin() as connection:
                for work in usable:
                    if work.source_work_id in seen:
                        continue
                    seen.add(work.source_work_id)
                    exists = connection.execute(
                        select(works.c.id).where(
                            works.c.source_id == "dlsite",
                            works.c.source_work_id == work.source_work_id,
                        )
                    ).first()
                    upsert_source_metadata(
                        connection,
                        work,
                        visibility="normal",
                        keep_missing=True,
                        acquired_at=acquired.get(work.source_work_id),
                    )
                    totals["updated" if exists else "added"] += 1
                    kinds[work.raw_kind or "?"] += 1
                totals["skipped"] += len(items) - len(usable)
                totals["processed"] += len(batch)
                connection.execute(
                    update(sync_jobs)
                    .where(sync_jobs.c.id == job_id)
                    .values(
                        state="reading",
                        processed=totals["processed"],
                        added=totals["added"],
                        updated=totals["updated"],
                        skipped=totals["skipped"],
                        missing=totals["processed"] - len(seen) - totals["skipped"],
                    )
                )
        logger.info("sync type codes: %s", ",".join(f"{k}={v}" for k, v in sorted(kinds.items())))
        self._check(generation)
        now = _now()
        with self._engine.begin() as connection:
            # Only a complete read can say what is no longer listed, and even then the
            # work and its records stay: it is a note, not a deletion.
            if totals["skipped"] == 0:
                listed = select(works.c.id).where(
                    works.c.source_id == "dlsite", works.c.source_work_id.in_(seen)
                )
                dlsite_works = select(works.c.id).where(works.c.source_id == "dlsite")
                connection.execute(
                    update(library_entries)
                    .where(
                        library_entries.c.work_id.in_(dlsite_works),
                        library_entries.c.work_id.not_in(listed),
                    )
                    .values(ownership_status="not_currently_observed")
                )
                connection.execute(
                    update(source_accounts)
                    .where(source_accounts.c.id == DLSITE_ACCOUNT_ID)
                    .values(last_synced_at=now)
                )
            connection.execute(
                update(sync_jobs)
                .where(sync_jobs.c.id == job_id)
                .values(
                    state="partial" if totals["skipped"] else "succeeded",
                    error_code="some_unreadable" if totals["skipped"] else None,
                    finished_at=now,
                )
            )
