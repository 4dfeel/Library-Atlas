"""Checks for changed works once a day, by running the ordinary sync: the user asked for this,
and turned it on or off in one place. It only learns that something changed. It never
downloads, and it never logs in: without a working session it quietly waits for the next round.
"""

import threading
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, select

from app.api import models
from app.core.errors import AtlasError
from app.db.engine import writing
from app.db.schema import source_accounts
from app.repositories import app_settings
from app.repositories.accounts import DLSITE_ACCOUNT_ID
from app.services.dlsite_sync import DlsiteSync

_SETTING = "updates.auto_check"
_INTERVAL = timedelta(hours=24)
_FIRST_LOOK_SECONDS = 60.0  # Not during startup, when the user is doing something else.
_LOOK_EVERY_SECONDS = 3600.0


class UpdateChecker:
    def __init__(self, engine: Engine, sync: DlsiteSync) -> None:
        self._engine = engine
        self._sync = sync
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def status(self) -> models.UpdateSettings:
        with self._engine.connect() as connection:
            value = app_settings.get(connection, _SETTING)
            last = connection.execute(
                select(source_accounts.c.last_synced_at).where(
                    source_accounts.c.id == DLSITE_ACCOUNT_ID
                )
            ).scalar()
        return models.UpdateSettings(auto_check=value != "0", last_checked_at=last)

    def set_auto(self, enabled: bool) -> models.UpdateSettings:
        with writing(self._engine).begin() as connection:
            app_settings.put(connection, _SETTING, "1" if enabled else "0")
        return self.status()

    def tick(self, now: datetime | None = None) -> bool:
        """One look. True when it started a check."""
        status = self.status()
        if not status.auto_check:
            return False
        if status.last_checked_at:
            try:
                last = datetime.fromisoformat(status.last_checked_at)
            except ValueError:
                last = datetime.min.replace(tzinfo=UTC)
            if (now or datetime.now(UTC)) - last < _INTERVAL:
                return False
        try:
            self._sync.start()
        except AtlasError:
            return False  # Not signed in, or signing in right now. Next round.
        return True

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="update-check", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        wait = _FIRST_LOOK_SECONDS
        while not self._stop.wait(wait):
            self.tick()
            wait = _LOOK_EVERY_SECONDS
