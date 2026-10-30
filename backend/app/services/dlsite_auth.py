"""DLsite connection lifecycle. One attempt at a time; a result only counts while its
attempt is still current, so a cancelled or replaced login can never save a session.

Persisted state says what was last established. What is happening right now, and what
the last check found, is held here and combined when the state is read. Being signed in,
being safely stored and being verifiable right now stay separate facts.
"""

import hashlib
import json
import logging
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.dlsite.login_host import LoginHost, LoginProcess, LoginRequest
from app.adapters.dlsite.session import (
    SessionCheck,
    SessionChecker,
    SessionCookie,
    decode_session,
    encode_session,
    session_cookies,
)
from app.api import models
from app.core.credentials import CredentialStore, CredentialStoreError
from app.core.errors import AtlasError
from app.core.session_vault import SessionCorrupt, SessionVault
from app.repositories import accounts, app_settings

logger = logging.getLogger("atlas")

MESSAGES = {
    "bad_credentials": "账号或密码不正确，请检查后重试。",
    "form_changed": "DLsite 的登录方式可能有变化，暂时无法在 Atlas 内登录。可以改用网页登录。",
    "browser_unavailable": "无法启动登录组件。请确认已安装 Edge WebView2 Runtime 后重试。",
    "timeout": "登录等待超时，请重试。",
    "cancelled": "已取消登录。",
    "not_confirmed": "没能确认登录成功，请重试。",
    "store_failed": "登录成功了，但无法安全保存会话，所以没有保持连接。请重试。",
    "store_unavailable": "暂时无法读取系统凭据存储，连接状态未知。你的账号没有问题，请稍后重试。",
    "session_missing": "保存的登录信息已不可用，请重新登录。",
    "session_expired": "登录已失效，请重新登录。",
    "platform_unavailable": "暂时无法连接 DLsite 验证登录状态。这不代表登录已失效。",
    "disconnect_failed": "已停用这个登录，不会再被使用，但清理系统凭据时出错。请重试退出登录。",
    "saved_login_rejected": "保存的密码已失效，已删除。请重新输入。",
    "remember_failed": "已登录，但没能保存账号密码，下次需要重新输入。",
}
_REMEMBERED_ALIAS = "dlsite.remembered_alias"


@dataclass
class _Attempt:
    id: int
    process: LoginProcess | None = None
    needs_verification: bool = False
    fingerprint: str | None = None
    alias: str | None = None
    # Held only until the login ends, and only when the user asked to be remembered.
    remember: bytes | None = field(default=None, repr=False)
    from_saved: bool = False


def mask_account(login_id: str) -> str:
    """Enough to recognize your own account, and useless to anyone else."""
    name, at, domain = login_id.strip().partition("@")
    return f"{name[:3]}•••{at}{domain}"


class DlsiteAuth:
    def __init__(
        self,
        engine: Engine,
        store: CredentialStore,
        host: LoginHost,
        checker: SessionChecker,
        browser_dir: Path,
    ) -> None:
        self._engine = engine
        self._host = host
        self._checker = checker
        self._browser_dir = browser_dir
        self._lock = threading.RLock()
        self._attempt: _Attempt | None = None
        self._next_attempt = 0
        self._generation = 0  # Bumped by login and disconnect; stale checks are discarded.
        self._checking = False
        self._problem: str | None = None
        self._unverified = False
        with engine.connect() as connection:
            self._library_id = accounts.library_id(connection)
        self._vault = SessionVault(store, f"{self._library_id}/dlsite/session")
        # In the credential store only, by the user's choice. Read only to log in.
        self._saved_login = SessionVault(store, f"{self._library_id}/dlsite/login")

    # --- reading ---

    def connection(self) -> models.DlsiteConnection:
        with self._engine.connect() as connection:
            row = accounts.get_account(connection)
            remembered = app_settings.get(connection, _REMEMBERED_ALIAS)
        persisted = row.state if row else "not_connected"
        cleanup = bool(row.cleanup_pending) if row else False
        with self._lock:
            attempt = self._attempt
            if attempt is not None:
                state = "needs_verification" if attempt.needs_verification else "authenticating"
            elif self._checking:
                state = "verifying"
            elif cleanup:
                state = "disconnect_failed"
            elif persisted == "connected" and self._unverified:
                state = "unverified"
            else:
                state = persisted
            problem = self._problem
        return models.DlsiteConnection(
            state=cast(models.ConnectionState, state),
            message=MESSAGES.get(problem) if problem else None,
            code=problem,
            last_verified_at=row.last_verified_at if row else None,
            can_reveal=attempt is not None and attempt.needs_verification,
            account_alias=row.account_alias if row and persisted == "connected" else None,
            remembered_account=remembered,
        )

    def summary_state(self) -> models.ConnectionState:
        return self.connection().state

    # --- login ---

    def _fingerprint(self, login_id: str) -> str:
        normalized = login_id.strip().casefold()
        return hashlib.sha256(f"{self._library_id}:{normalized}".encode()).hexdigest()

    def _begin(
        self,
        request: LoginRequest,
        fingerprint: str | None,
        alias: str | None = None,
        *,
        remember: bytes | None = None,
        from_saved: bool = False,
    ) -> models.DlsiteConnection:
        with self._lock:
            if self._attempt is not None:
                raise AtlasError("login_in_progress", "已经有一次登录正在进行。", status=409)
            self._next_attempt += 1
            self._generation += 1
            attempt = _Attempt(
                id=self._next_attempt,
                fingerprint=fingerprint,
                alias=alias,
                remember=remember,
                from_saved=from_saved,
            )
            self._attempt = attempt
            self._problem = None
            self._unverified = False
        threading.Thread(
            target=self._run, args=(attempt, request), name="dlsite-login", daemon=True
        ).start()
        return self.connection()

    def start_login(
        self,
        login_id: str,
        password: str,
        *,
        confirm_switch: bool,
        remember: bool = False,
        from_saved: bool = False,
    ) -> models.DlsiteConnection:
        fingerprint = self._fingerprint(login_id)
        with self._engine.connect() as connection:
            row = accounts.get_account(connection)
        known = row.account_fingerprint if row else None
        if known and known != fingerprint and not confirm_switch:
            raise AtlasError(
                "account_mismatch",
                "这个账号和之前连接的不是同一个。确认后才会切换；已有的作品不会被删除。",
                status=409,
            )
        return self._begin(
            LoginRequest("credentials", self._browser_dir, login_id, password),
            fingerprint,
            mask_account(login_id),
            remember=(
                json.dumps({"login_id": login_id, "password": password}).encode()
                if remember
                else None
            ),
            from_saved=from_saved,
        )

    def start_saved_login(self) -> models.DlsiteConnection:
        try:
            raw = self._saved_login.load()
            saved = json.loads(raw) if raw else None
            if saved is None:
                raise ValueError
            login_id, password = saved["login_id"], saved["password"]
        except CredentialStoreError:
            raise AtlasError(
                "credential_store_unavailable", "暂时无法读取系统凭据存储。", status=503
            ) from None
        except (SessionCorrupt, ValueError, KeyError, TypeError):
            self.forget_saved_login()
            raise AtlasError(
                "no_saved_login", "没有可用的已保存账号，请重新输入。", status=409
            ) from None
        return self.start_login(login_id, password, confirm_switch=True, from_saved=True)

    def forget_saved_login(self) -> models.DlsiteConnection:
        try:
            self._saved_login.delete()
        except CredentialStoreError:
            raise AtlasError(
                "credential_store_unavailable", "无法删除保存的账号密码，请重试。", status=503
            ) from None
        with self._engine.begin() as connection:
            app_settings.delete(connection, _REMEMBERED_ALIAS)
        return self.connection()

    def start_window_login(self) -> models.DlsiteConnection:
        # The account cannot be identified here: its name stays inside the platform's page.
        return self._begin(LoginRequest("window", self._browser_dir), None)

    def _current(self, attempt: _Attempt) -> bool:
        return self._attempt is attempt

    def _run(self, attempt: _Attempt, request: LoginRequest) -> None:
        outcome = "browser_unavailable"
        cookies: list[SessionCookie] = []
        try:
            process = self._host.start(request)
            with self._lock:
                attempt.process = process
                if not self._current(attempt):
                    process.cancel()
            for event in process.events():
                if event.kind == "state":
                    with self._lock:
                        if self._current(attempt):
                            attempt.needs_verification = event.value == "needs_verification"
                elif event.kind == "page":
                    logger.info("login page: %s", event.value)
                else:
                    outcome = event.value
                    cookies = session_cookies(event.cookies)
        except OSError:
            outcome = "browser_unavailable"
        except Exception as error:  # noqa: BLE001 - must end the attempt; type only, no values.
            logger.error("login attempt failed: %s", type(error).__name__)
        self._remove_browser_data()
        if outcome == "success" and cookies:
            self._finish_login(attempt, cookies)
            return
        problem = "not_confirmed" if outcome == "success" else outcome
        with self._lock:
            if self._current(attempt):
                if outcome == "bad_credentials" and attempt.from_saved:
                    # Never send a known-bad password again: that is how accounts get locked.
                    self.forget_saved_login()
                    problem = "saved_login_rejected"
                self._attempt = None
                self._problem = None if problem == "cancelled" else problem

    def _finish_login(self, attempt: _Attempt, cookies: list[SessionCookie]) -> None:
        result = self._checker.check(cookies)  # No lock: this is a network call.
        with self._lock:
            if not self._current(attempt):
                return  # Cancelled or replaced while checking: discard, save nothing.
            if result is SessionCheck.EXPIRED:
                self._attempt = None
                self._problem = "not_confirmed"
                return
            try:
                self._vault.save(encode_session(cookies))
                with self._engine.begin() as connection:
                    accounts.save_connected(
                        connection,
                        credential_ref=f"{self._library_id}/dlsite/session",
                        fingerprint=attempt.fingerprint,
                        alias=attempt.alias,
                        verified=result is SessionCheck.VALID,
                    )
            except (CredentialStoreError, SQLAlchemyError) as error:
                logger.error("session not saved: %s", type(error).__name__)
                self._attempt = None
                self._problem = "store_failed"
                return
            self._attempt = None
            self._unverified = result is SessionCheck.UNAVAILABLE
            self._problem = "platform_unavailable" if self._unverified else None
            if attempt.remember is not None:
                try:
                    self._saved_login.save(attempt.remember)
                    with self._engine.begin() as connection:
                        app_settings.put(connection, _REMEMBERED_ALIAS, attempt.alias or "")
                except (CredentialStoreError, SQLAlchemyError) as error:
                    logger.error("login not remembered: %s", type(error).__name__)
                    self._problem = "remember_failed"
                attempt.remember = None

    def cancel(self) -> models.DlsiteConnection:
        with self._lock:
            attempt = self._attempt
            self._attempt = None  # From here on, this attempt's result is ignored.
            self._problem = None
        if attempt is not None and attempt.process is not None:
            attempt.process.cancel()
        return self.connection()

    def reveal(self) -> models.DlsiteConnection:
        with self._lock:
            process = self._attempt.process if self._attempt else None
        if process is not None:
            process.reveal()
        return self.connection()

    # --- session check ---

    def verify(self) -> models.DlsiteConnection:
        with self._lock:
            if self._attempt is not None or self._checking:
                return self.connection()
            self._checking = True
            generation = self._generation
        threading.Thread(
            target=self._check, args=(generation,), name="dlsite-check", daemon=True
        ).start()
        return self.connection()

    def restore(self) -> None:
        """One check at startup. A stored record alone never counts as connected."""
        with self._engine.connect() as connection:
            row = accounts.get_account(connection)
        if row is None:
            return
        if row.cleanup_pending:
            self._cleanup()
        elif row.state == "connected":
            self.verify()

    def _check(self, generation: int) -> None:
        problem: str | None = None
        result: SessionCheck | None = None
        try:
            raw = self._vault.load()
            if raw is None:
                problem = "session_missing"
            else:
                result = self._checker.check(decode_session(raw))
        except CredentialStoreError:
            problem = "store_unavailable"
        except (SessionCorrupt, ValueError):
            problem = "session_missing"
        with self._lock:
            self._checking = False
            if generation != self._generation:
                return  # A login or disconnect happened meanwhile; this answer is stale.
            self._unverified = False
            self._problem = problem
            if result is SessionCheck.VALID:
                with self._engine.begin() as connection:
                    accounts.mark_verified(connection)
            elif result is SessionCheck.UNAVAILABLE:
                self._unverified = True
                self._problem = "platform_unavailable"
            elif result is SessionCheck.EXPIRED or problem == "session_missing":
                self._problem = "session_expired" if result else problem
                with self._engine.begin() as connection:
                    accounts.set_state(connection, "reauth_required")
            elif problem == "store_unavailable":
                self._unverified = True

    # --- disconnect ---

    def disconnect(self) -> models.DlsiteConnection:
        self.cancel()
        with self._lock:
            self._generation += 1
            self._unverified = False
            self._problem = None
            with self._engine.begin() as connection:
                accounts.disable(connection)
        self._cleanup()
        return self.connection()

    def _cleanup(self) -> None:
        try:
            self._vault.delete()
        except CredentialStoreError:
            with self._lock:
                self._problem = "disconnect_failed"
            return
        self._remove_browser_data()
        with self._engine.begin() as connection:
            accounts.cleanup_done(connection)
        with self._lock:
            self._problem = None

    def _remove_browser_data(self) -> None:
        shutil.rmtree(self._browser_dir, ignore_errors=True)

    def shutdown(self) -> None:
        with self._lock:
            attempt = self._attempt
            self._attempt = None
        if attempt is not None and attempt.process is not None:
            attempt.process.cancel()
