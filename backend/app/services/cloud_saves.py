"""Game saves in the user's own Google Drive: immutable snapshots, restored only when asked.

A snapshot is a data file plus a commit file: the commit goes up only after the data has been
uploaded and checked, so only committed snapshots can ever be restored. Each records its parents.
Which copy is newer is decided from that history and the content, never from clocks, so two
computers working from one snapshot leave two branches, both restorable, until the user chooses.
Nothing here deletes anything in Drive, and nothing touches a local save without backing it up.
"""

import hashlib
import json
import logging
import os
import platform
import shutil
import threading
import time
import uuid
import webbrowser
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import Engine, Row, delete, select, update
from sqlalchemy.dialects.sqlite import insert

from app.adapters.google.drive import (
    DriveAuthProblem,
    DriveClient,
    DriveProblem,
    DriveQuotaFull,
    DriveUnreachable,
)
from app.adapters.google.oauth import (
    GoogleAuthFailed,
    GoogleUnreachable,
    LoopbackAttempt,
    exchange_code,
    refresh_access,
)
from app.adapters.system.archives import ArchiveProblem, safe_parts
from app.api import models
from app.core.config import Settings
from app.core.credentials import CredentialStore, CredentialStoreError
from app.core.errors import AtlasError
from app.db.engine import writing
from app.db.schema import cloud_outbox, cloud_states, local_copies
from app.repositories import app_settings
from app.repositories.works import get_ordinary_work
from app.services.game_updates import GameUpdater, SavedFile

logger = logging.getLogger("atlas")

NS_KEY = "atlasNamespace"
NAMESPACE = "library-atlas-saves-v1"
SCHEMA = 1
FOLDER_NAME = "Library Atlas 云存档"
MAX_FILES = 50_000
MAX_BYTES = 8 * 1024 * 1024 * 1024
_REFRESH_NAME = "google/refresh"
_SECRET_NAME = "google/client-secret"  # noqa: S105 - where it is kept, not what it is.
_K_CLIENT = "cloud.client_id"
_K_ACCOUNT = "cloud.account_id"
_K_NAME = "cloud.account_name"
_K_FOLDER = "cloud.folder_id"
_K_DEVICE = "cloud.device_id"
_K_AUTO_CHECK = "cloud.auto_check"
_K_AUTO_BACKUP = "cloud.auto_backup"
_WORKER_WAIT = 60.0
_MAX_ATTEMPTS = 5
_STATES_BUSY = ("queued", "uploading")
MESSAGES = {
    "not_connected": "还没有连接 Google Drive。",
    "needs_auth": "Google 授权已失效，请在设置里重新连接。",
    "offline": "现在连不上 Google Drive。本地存档不受影响。",
    "quota": "Google Drive 空间不足。本地存档不受影响，快照会留着等你腾出空间后重试。",
    "error": "Google Drive 返回了意料之外的结果，没有上传或修改任何东西。",
    "changing": "存档正在变化，可能游戏还在写入。请关闭游戏后再试。",
    "too_large": "存档太大，不会上传。请检查存档位置是否选得太宽。",
    "empty": "现在没有存档文件，没有东西可以上传。",
    "config": "这份快照的存档位置和这里的设置不一样，不能直接恢复。",
    "damaged": "这份快照下载后校验不通过，没有修改本地存档。",
    "unknown_schema": "这份快照来自更新版本的 Atlas，无法在这里恢复。",
    "closed": "请先关闭游戏并确认。",
    "not_found": "云端找不到这份快照。",
    "storage": "Windows 凭据存储不可用，无法保存授权。",
}


class _Problem(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _digest(files: list[SavedFile], hashes: dict[str, str]) -> str:
    lines = sorted(f"{item.rule}\0{item.relative}\0{hashes[item.stored]}" for item in files)
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def _hash_file(path: Path, algorithm: str = "sha256") -> str:
    hasher = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def fingerprint(rules: list[dict[str, str]]) -> str:
    """What must match for a snapshot to fit: a place outside the game is matched by position,
    since its full path differs from one computer to the next."""
    shape = [(rule["kind"], "" if rule["kind"] == "outside" else rule["path"]) for rule in rules]
    return hashlib.sha256(json.dumps(shape, ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True)
class Snapshot:
    id: str
    parents: tuple[str, ...]
    digest: str
    manifest: dict[str, Any]
    commit_id: str


def classify(
    local: str | None, base: str | None, base_digest: str | None, snapshots: list[Snapshot]
) -> tuple[str, list[Snapshot]]:
    """The whole decision, from history and content alone. Returns the state and the heads."""
    named = {item.id: item for item in snapshots}
    has_child = {parent for item in snapshots for parent in item.parents}
    heads = [item for item in snapshots if item.id not in has_child]
    if not snapshots:
        return ("local_only" if local else "empty"), []
    if len(heads) > 1:
        return "conflict", heads
    if not heads:
        # Only a cycle does this, and nothing Atlas writes makes one.
        return "conflict", list(snapshots)
    head = heads[0]
    if local is not None and local == head.digest:
        return "synced", heads
    if base == head.id:
        return ("cloud_update" if local is None else "local_changed"), heads
    ancestors: set[str] = set()
    walk = list(head.parents)
    while walk:
        current = walk.pop()
        if current not in ancestors:
            ancestors.add(current)
            if current in named:
                walk.extend(named[current].parents)
    if local is None:
        return "cloud_update", heads
    if base in ancestors and local == base_digest:
        return "cloud_update", heads
    return "conflict", heads


class CloudSaves:
    def __init__(
        self,
        engine: Engine,
        settings: Settings,
        updater: GameUpdater,
        store: CredentialStore | None,
        *,
        transport: httpx.BaseTransport | None = None,
        browser: Callable[[str], Any] = webbrowser.open,
        sleep: Callable[[float], None] = time.sleep,
        device_name: str | None = None,
    ) -> None:
        self._engine = engine
        self._updater = updater
        self._store = store
        self._transport = transport
        self._browser = browser
        self._sleep = sleep
        self._device_name = device_name or platform.node() or "这台电脑"
        self._outbox = settings.data_dir / "cloud-outbox"
        self._staging = settings.data_dir / "cloud-staging"
        self._lock = threading.Lock()
        self._work_lock = threading.Lock()
        self._access: tuple[str, float] | None = None
        self._attempt: LoopbackAttempt | None = None
        self._generation = 0
        self._sign_in_problem: str | None = None
        self._manifests: dict[str, dict[str, Any]] = {}
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._queue_lock = threading.Lock()
        # Tests send the queue themselves, to put trouble at an exact point.
        self.send_in_background = True
        # A game may write a little more on its way out.
        self.after_exit_seconds = 15.0

    # --- start and stop ---

    def start(self) -> None:
        with writing(self._engine).begin() as connection:
            connection.execute(
                update(cloud_outbox)
                .where(cloud_outbox.c.state == "uploading")
                .values(state="queued")
            )
        shutil.rmtree(self._staging, ignore_errors=True)
        self._thread = threading.Thread(target=self._worker, name="cloud-saves", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._attempt is not None:
            self._attempt.cancel()
        if self._thread is not None:
            self._thread.join(timeout=10)

    # --- settings and sign-in ---

    def _get(self, key: str) -> str | None:
        with self._engine.connect() as connection:
            return app_settings.get(connection, key)

    def _put(self, key: str, value: str) -> None:
        with writing(self._engine).begin() as connection:
            app_settings.put(connection, key, value)

    def _device(self) -> str:
        device = self._get(_K_DEVICE)
        if device is None:
            device = uuid.uuid4().hex
            self._put(_K_DEVICE, device)
        return device

    def _read_secret(self, name: str) -> str | None:
        if self._store is None:
            return None
        try:
            raw = self._store.read(name)
        except CredentialStoreError:
            return None
        return raw.decode() if raw else None

    def _connected(self) -> bool:
        return bool(self._get(_K_ACCOUNT)) and self._read_secret(_REFRESH_NAME) is not None

    def status(self) -> models.CloudStatus:
        attempt = self._attempt
        return models.CloudStatus(
            configured=bool(self._get(_K_CLIENT)),
            connected=self._connected(),
            connecting=attempt is not None and not attempt.finished,
            problem=self._sign_in_problem,
            account_name=self._get(_K_NAME) if self._connected() else None,
            device_name=self._device_name,
            auto_check=self._get(_K_AUTO_CHECK) == "1",
            auto_backup=self._get(_K_AUTO_BACKUP) == "1",
        )

    def set_client(self, body: models.CloudClientIn) -> models.CloudStatus:
        if self._store is None:
            raise AtlasError("cloud_storage", MESSAGES["storage"], status=409)
        client_id = body.client_id.strip()
        try:
            if body.client_secret and body.client_secret.strip():
                self._store.write(_SECRET_NAME, body.client_secret.strip().encode())
            else:
                self._store.delete(_SECRET_NAME)
        except CredentialStoreError:
            raise AtlasError("cloud_storage", MESSAGES["storage"], status=409) from None
        self._put(_K_CLIENT, client_id)
        return self.status()

    def set_options(self, body: models.CloudOptionsIn) -> models.CloudStatus:
        self._put(_K_AUTO_CHECK, "1" if body.auto_check else "0")
        self._put(_K_AUTO_BACKUP, "1" if body.auto_backup else "0")
        return self.status()

    def connect(self) -> models.CloudStatus:
        client_id = self._get(_K_CLIENT)
        if not client_id:
            raise AtlasError("cloud_not_configured", "请先填写 OAuth 客户端 ID。", status=409)
        if self._store is None:
            raise AtlasError("cloud_storage", MESSAGES["storage"], status=409)
        with self._lock:
            if self._attempt is not None:
                self._attempt.cancel()
            self._generation += 1
            generation = self._generation
            self._sign_in_problem = None

            def answered(code: str | None, verifier: str, redirect_uri: str) -> str:
                return self._finish_sign_in(generation, client_id, code, verifier, redirect_uri)

            self._attempt = LoopbackAttempt(client_id, answered)
            self._attempt.start()
            url = self._attempt.url
        self._browser(url)
        return self.status()

    def _finish_sign_in(
        self, generation: int, client_id: str, code: str | None, verifier: str, redirect: str
    ) -> str:
        with self._lock:
            if generation != self._generation:
                return "这个登录请求已失效，请回到 Library Atlas 重新连接。"
        if not code:
            self._sign_in_problem = "你取消了授权，没有连接 Google Drive。"
            return "已取消。可以关闭这个页面。"
        assert self._store is not None
        try:
            tokens = exchange_code(
                client_id,
                self._read_secret(_SECRET_NAME),
                code,
                verifier,
                redirect,
                self._transport,
            )
            if not tokens.refresh:
                raise GoogleAuthFailed
            self._store.write(_REFRESH_NAME, tokens.refresh.encode())
            self._access = (tokens.access, time.monotonic() + tokens.expires_in - 60)
            user = self._drive().about()
        except (GoogleAuthFailed, DriveAuthProblem):
            self._sign_in_problem = "Google 拒绝了这次授权，请重试。"
            return "授权没有完成，请回到 Library Atlas 重试。"
        except (GoogleUnreachable, DriveUnreachable, DriveProblem):
            self._sign_in_problem = "连不上 Google，请稍后重试。"
            return "连不上 Google，请回到 Library Atlas 重试。"
        except CredentialStoreError:
            self._sign_in_problem = MESSAGES["storage"]
            return "无法保存授权，请回到 Library Atlas 查看。"
        account = str(user["permissionId"])
        if self._get(_K_ACCOUNT) != account:
            # Another account's folder is not this one's. Its queued uploads wait for it.
            with writing(self._engine).begin() as connection:
                app_settings.delete(connection, _K_FOLDER)
            self._manifests.clear()
        self._put(_K_ACCOUNT, account)
        self._put(_K_NAME, str(user.get("displayName") or "Google 账号"))
        self._wake.set()
        return "已连接 Google Drive。可以关闭这个页面，回到 Library Atlas。"

    def disconnect(self) -> models.CloudStatus:
        """This computer's access only. What is in Drive and on disk stays, and other computers
        keep working, which is why the grant itself is not revoked."""
        with self._lock:
            self._generation += 1
            if self._attempt is not None:
                self._attempt.cancel()
            self._access = None
        if self._store is not None:
            try:
                self._store.delete(_REFRESH_NAME)
            except CredentialStoreError:
                raise AtlasError("cloud_storage", MESSAGES["storage"], status=409) from None
        with writing(self._engine).begin() as connection:
            app_settings.delete(connection, _K_ACCOUNT)
            app_settings.delete(connection, _K_NAME)
            app_settings.delete(connection, _K_FOLDER)
        self._manifests.clear()
        return self.status()

    def _token(self, force: bool) -> str:
        with self._lock:
            if not force and self._access is not None and time.monotonic() < self._access[1]:
                return self._access[0]
        refresh = self._read_secret(_REFRESH_NAME)
        client_id = self._get(_K_CLIENT)
        if refresh is None or client_id is None:
            raise DriveAuthProblem
        try:
            tokens = refresh_access(
                client_id, self._read_secret(_SECRET_NAME), refresh, self._transport
            )
        except GoogleAuthFailed:
            raise DriveAuthProblem from None
        except GoogleUnreachable:
            raise DriveUnreachable from None
        with self._lock:
            self._access = (tokens.access, time.monotonic() + tokens.expires_in - 60)
            return tokens.access

    def _drive(self) -> DriveClient:
        return DriveClient(self._token, self._transport, sleep=self._sleep)

    def _folder(self, drive: DriveClient) -> str:
        """Found by the mark Atlas put on it, never by its name, which anyone can reuse."""
        known = self._get(_K_FOLDER)
        marked = drive.find({NS_KEY: NAMESPACE, "kind": "folder"})
        if known and any(item["id"] == known for item in marked):
            return known
        if marked:
            chosen = min(marked, key=lambda item: str(item.get("createdTime", "")))
        else:
            chosen = drive.create_folder(FOLDER_NAME, {NS_KEY: NAMESPACE, "kind": "folder"})
        self._put(_K_FOLDER, str(chosen["id"]))
        return str(chosen["id"])

    # --- what is there ---

    def _work(self, work_id: str) -> tuple[Row[Any], Row[Any] | None]:
        with self._engine.connect() as connection:
            work = get_ordinary_work(connection, work_id)
            copy = connection.execute(
                select(local_copies)
                .where(local_copies.c.work_id == work_id)
                .order_by(local_copies.c.is_default.desc(), local_copies.c.created_at)
                .limit(1)
            ).first()
        return work, copy

    def _local(
        self, root: Path, rules: list[dict[str, str]]
    ) -> tuple[list[SavedFile], dict[str, str]]:
        files = self._updater.saved_files(root, rules)
        if len(files) > MAX_FILES or sum(item.size for item in files) > MAX_BYTES:
            raise _Problem("too_large")
        return files, {item.stored: _hash_file(item.path) for item in files}

    def _snapshots(self, drive: DriveClient, source_work_id: str) -> list[Snapshot]:
        """Every committed snapshot, or an exception. A commit that cannot be read is an error,
        since treating it as absent could make a branch vanish."""
        commits = drive.find({NS_KEY: NAMESPACE, "kind": "commit", "work": source_work_id})
        found = []
        for commit in commits:
            manifest = self._manifests.get(commit["id"])
            if manifest is None:
                manifest = drive.read_json(commit["id"])
                if not isinstance(manifest, dict):
                    raise DriveProblem
                self._manifests[commit["id"]] = manifest
            found.append(
                Snapshot(
                    id=str(manifest.get("snapshot") or commit["id"]),
                    parents=tuple(str(item) for item in manifest.get("parents", [])),
                    digest=str(manifest.get("digest", "")),
                    manifest=manifest,
                    commit_id=commit["id"],
                )
            )
        return found

    def _state(self, account: str, work_id: str) -> Row[Any] | None:
        with self._engine.connect() as connection:
            return connection.execute(
                select(cloud_states).where(
                    cloud_states.c.account_id == account, cloud_states.c.work_id == work_id
                )
            ).first()

    def _set_state(self, account: str, work_id: str, **values: Any) -> None:
        values["updated_at"] = _now()
        with writing(self._engine).begin() as connection:
            connection.execute(
                insert(cloud_states)
                .values(account_id=account, work_id=work_id, **values)
                .on_conflict_do_update(
                    index_elements=[cloud_states.c.account_id, cloud_states.c.work_id],
                    set_=values,
                )
            )

    def _pending(self, account: str, work_id: str) -> list[Row[Any]]:
        with self._engine.connect() as connection:
            return list(
                connection.execute(
                    select(cloud_outbox)
                    .where(cloud_outbox.c.account_id == account, cloud_outbox.c.work_id == work_id)
                    .order_by(cloud_outbox.c.created_at)
                )
            )

    def _snapshot_out(self, item: Snapshot, heads: set[str], shape: str) -> models.CloudSnapshotOut:
        device = item.manifest.get("device") or {}
        files = item.manifest.get("files") or []
        return models.CloudSnapshotOut(
            id=item.id,
            device_name=str(device.get("name") or "未知设备"),
            this_device=device.get("id") == self._get(_K_DEVICE),
            created_at=str(item.manifest.get("created_at") or ""),
            files=len(files),
            size_bytes=sum(int(entry.get("size", 0)) for entry in files),
            is_head=item.id in heads,
            restorable=item.manifest.get("schema") == SCHEMA
            and item.manifest.get("fingerprint") == shape,
            is_current=False,
        )

    def work_status(self, work_id: str) -> models.CloudWorkOut:
        work, copy = self._work(work_id)
        auto_check = self._get(_K_AUTO_CHECK) == "1"

        def out(state: str, **values: Any) -> models.CloudWorkOut:
            return models.CloudWorkOut(
                state=state,
                message=MESSAGES.get(state),
                auto_check=auto_check,
                **values,
            )

        account = self._get(_K_ACCOUNT)
        if not self._connected() or account is None:
            return out("not_connected")
        config = self._updater.save_config(work_id)
        rules = [rule.model_dump() for rule in config.rules]
        if not rules:
            return out("no_saves" if config.confirmed_none else "unconfigured")
        if copy is None:
            return out("no_copy")
        root = Path(copy.root_path)
        if not root.is_dir():
            return out("folder_offline")
        state = self._state(account, work_id)
        pending = self._pending(account, work_id)
        queue = models.CloudQueueOut(
            count=len(pending),
            uploading=any(item.state == "uploading" for item in pending),
            failed=next((item.code for item in pending if item.state == "failed"), None),
        )
        try:
            files, hashes = self._local(root, rules)
        except _Problem as problem:
            return out(problem.code)
        local = _digest(files, hashes) if files else None
        local_summary = {
            "local_files": len(files),
            "local_bytes": sum(item.size for item in files),
            "queue": queue,
        }
        if state is not None and state.restoring:
            return out("restore_interrupted", **local_summary)
        try:
            snapshots = self._snapshots(self._drive(), work.source_work_id)
        except DriveAuthProblem:
            return out("needs_auth", **local_summary)
        except DriveUnreachable:
            return out("offline", **local_summary)
        except DriveProblem:
            return out("error", **local_summary)
        base = state.base_snapshot if state is not None else None
        base_digest = state.base_digest if state is not None else None
        decided, heads = classify(local, base, base_digest, snapshots)
        if decided == "synced" and heads and base != heads[0].id:
            self._set_state(
                account, work_id, base_snapshot=heads[0].id, base_digest=heads[0].digest
            )
            base = heads[0].id
        if queue.failed:
            decided = queue.failed if queue.failed in MESSAGES else "error"
        elif pending and decided != "conflict":
            decided = "uploading" if queue.uploading else "pending"
        shape = fingerprint(rules)
        head_ids = {item.id for item in heads}
        history = [
            self._snapshot_out(item, head_ids, shape).model_copy(
                update={"is_current": item.id == base}
            )
            for item in sorted(
                snapshots, key=lambda item: str(item.manifest.get("created_at", "")), reverse=True
            )
        ]
        return out(decided, history=history, **local_summary)

    # --- making a snapshot ---

    def backup(self, work_id: str, parents: list[str] | None = None) -> models.CloudWorkOut:
        account = self._get(_K_ACCOUNT)
        if not self._connected() or account is None:
            raise AtlasError("cloud_not_connected", MESSAGES["not_connected"], status=409)
        work, copy = self._work(work_id)
        rules = [rule.model_dump() for rule in self._updater.save_config(work_id).rules]
        if not rules:
            raise AtlasError("cloud_unconfigured", "请先设置存档位置。", status=409)
        if copy is None or not Path(copy.root_path).is_dir():
            raise AtlasError("cloud_folder", "游戏文件夹现在不可用。", status=409)
        try:
            self._pack(work, account, Path(copy.root_path), rules, parents)
        except _Problem as problem:
            raise AtlasError(f"cloud_{problem.code}", MESSAGES[problem.code], status=409) from None
        self._wake.set()
        return self.work_status(work_id)

    def _pack(
        self,
        work: Row[Any],
        account: str,
        root: Path,
        rules: list[dict[str, str]],
        parents: list[str] | None,
    ) -> None:
        """Zipped from the files as they are, then read again: if anything changed meanwhile the
        game is probably still writing, and half a save must not look like a good one."""
        with self._work_lock:
            files, hashes = self._local(root, rules)
            if not files:
                raise _Problem("empty")
            digest = _digest(files, hashes)
            pending = self._pending(account, work.id)
            if any(item.digest == digest for item in pending):
                return
            state = self._state(account, work.id)
            if parents is None:
                if state is not None and state.base_digest == digest and not pending:
                    return
                if pending:
                    parents = [pending[-1].snapshot_id]
                elif state is not None and state.base_snapshot:
                    parents = [state.base_snapshot]
                else:
                    parents = []
            snapshot_id = uuid.uuid4().hex
            self._outbox.mkdir(parents=True, exist_ok=True)
            package = self._outbox / f"{snapshot_id}.zip"
            try:
                with zipfile.ZipFile(
                    package, "w", zipfile.ZIP_DEFLATED, allowZip64=True
                ) as archive:
                    for item in files:
                        archive.write(item.path, item.stored)
                again = self._updater.saved_files(root, rules)
                if _digest(again, {i.stored: _hash_file(i.path) for i in again}) != digest:
                    raise _Problem("changing")
                with zipfile.ZipFile(package) as archive:
                    if archive.testzip() is not None:
                        raise _Problem("changing")
            except _Problem:
                package.unlink(missing_ok=True)
                raise
            except (OSError, ValueError):
                package.unlink(missing_ok=True)
                raise _Problem("changing") from None
            manifest = {
                "schema": SCHEMA,
                "snapshot": snapshot_id,
                "work": work.source_work_id,
                "fingerprint": fingerprint(rules),
                "device": {"id": self._device(), "name": self._device_name},
                "created_at": _now(),
                "parents": parents,
                "digest": digest,
                "files": [
                    {
                        "rule": item.rule,
                        "relative": item.relative,
                        "stored": item.stored,
                        "size": item.size,
                        "sha256": hashes[item.stored],
                        "is_file_rule": item.is_file_rule,
                    }
                    for item in files
                ],
            }
            with writing(self._engine).begin() as connection:
                connection.execute(
                    cloud_outbox.insert().values(
                        snapshot_id=snapshot_id,
                        account_id=account,
                        work_id=work.id,
                        source_work_id=work.source_work_id,
                        digest=digest,
                        manifest=json.dumps(manifest, ensure_ascii=False),
                        state="queued",
                        attempts=0,
                        created_at=_now(),
                    )
                )

    # --- sending ---

    def _worker(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(_WORKER_WAIT)
            self._wake.clear()
            if self._stop.is_set():
                return
            if not self.send_in_background:
                continue
            try:
                self.run_queue()
            except Exception as error:  # noqa: BLE001 - the worker must outlive one bad turn.
                logger.error("cloud queue failed: %s", type(error).__name__)

    def run_queue(self) -> None:
        """Only this account's work: a queue left by another account waits for that account."""
        with self._queue_lock:
            self._run_queue()

    def _run_queue(self) -> None:
        account = self._get(_K_ACCOUNT)
        if account is None or not self._connected():
            return
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(cloud_outbox)
                .where(cloud_outbox.c.account_id == account, cloud_outbox.c.state == "queued")
                .order_by(cloud_outbox.c.created_at)
            ).all()
        for row in rows:
            if self._stop.is_set():
                return
            try:
                self._send(row, account)
            except DriveUnreachable:
                self._mark(row.snapshot_id, state="queued", code=None)
                return
            except DriveAuthProblem:
                self._mark(row.snapshot_id, state="failed", code="needs_auth")
                return
            except DriveQuotaFull:
                self._mark(row.snapshot_id, state="failed", code="quota")
            except (DriveProblem, _Problem, OSError) as error:
                logger.error("cloud upload failed: %s", type(error).__name__)
                attempts = row.attempts + 1
                self._mark(
                    row.snapshot_id,
                    state="failed" if attempts >= _MAX_ATTEMPTS else "queued",
                    code="error" if attempts >= _MAX_ATTEMPTS else None,
                    attempts=attempts,
                )

    def _mark(self, snapshot_id: str, **values: Any) -> None:
        with writing(self._engine).begin() as connection:
            connection.execute(
                update(cloud_outbox)
                .where(cloud_outbox.c.snapshot_id == snapshot_id)
                .values(**values)
            )

    def _send(self, row: Row[Any], account: str) -> None:
        """Can be repeated at any point. It first looks for what an earlier try already put up, so
        a lost answer or a restart makes neither a duplicate nor a false success."""
        self._mark(row.snapshot_id, state="uploading")
        drive = self._drive()
        marks = {NS_KEY: NAMESPACE, "work": row.source_work_id, "snapshot": row.snapshot_id}
        manifest = json.loads(row.manifest)
        package = self._outbox / f"{row.snapshot_id}.zip"
        committed = drive.find({**marks, "kind": "commit"})
        if not committed:
            size = package.stat().st_size
            md5 = _hash_file(package, "md5")
            folder = self._folder(drive)
            data = next(
                (
                    item
                    for item in drive.find({**marks, "kind": "data"})
                    if item.get("md5Checksum") == md5 and int(item.get("size", -1)) == size
                ),
                None,
            )
            if data is None:
                data = drive.upload(
                    f"{row.source_work_id}-{row.snapshot_id}.zip",
                    folder,
                    {**marks, "kind": "data"},
                    package,
                    "application/zip",
                )
                if data.get("md5Checksum") != md5 or int(data.get("size", -1)) != size:
                    raise _Problem("damaged")
            manifest["data"] = {"file_id": data["id"], "size": size, "md5": md5}
            drive.upload(
                f"{row.source_work_id}-{row.snapshot_id}.commit.json",
                folder,
                {**marks, "kind": "commit"},
                json.dumps(manifest, ensure_ascii=False).encode(),
                "application/json",
            )
        state = self._state(account, row.work_id)
        base = state.base_snapshot if state is not None else None
        parents = manifest.get("parents", [])
        # Becomes the base only if it follows from it. Otherwise it is a branch, and stays one.
        if base is None or base in parents:
            self._set_state(
                account, row.work_id, base_snapshot=row.snapshot_id, base_digest=row.digest
            )
        with writing(self._engine).begin() as connection:
            connection.execute(
                delete(cloud_outbox).where(cloud_outbox.c.snapshot_id == row.snapshot_id)
            )
        package.unlink(missing_ok=True)

    def retry(self, work_id: str) -> models.CloudWorkOut:
        self._work(work_id)
        with writing(self._engine).begin() as connection:
            connection.execute(
                update(cloud_outbox)
                .where(cloud_outbox.c.work_id == work_id, cloud_outbox.c.state == "failed")
                .values(state="queued", code=None, attempts=0)
            )
        self._wake.set()
        return self.work_status(work_id)

    # --- restoring ---

    def _find(
        self, drive: DriveClient, work: Row[Any], snapshot_id: str
    ) -> tuple[Snapshot, list[Snapshot]]:
        snapshots = self._snapshots(drive, work.source_work_id)
        match = next((item for item in snapshots if item.id == snapshot_id), None)
        if match is None:
            raise _Problem("not_found")
        return match, snapshots

    def _fetch(self, drive: DriveClient, item: Snapshot, folder: Path) -> dict[str, Path]:
        """Down to its own place and checked throughout. Nothing a snapshot says is trusted: names
        are checked, and only the files its list names, at the sizes it gives, are taken out."""
        data = item.manifest.get("data") or {}
        files = item.manifest.get("files") or []
        if not data.get("file_id") or len(files) > MAX_FILES:
            raise _Problem("damaged")
        package = folder / "snapshot.zip"
        limit = min(int(data.get("size", 0)), MAX_BYTES)
        drive.download(str(data["file_id"]), package, limit)
        if package.stat().st_size != data.get("size") or _hash_file(package, "md5") != data.get(
            "md5"
        ):
            raise _Problem("damaged")
        out: dict[str, Path] = {}
        try:
            with zipfile.ZipFile(package) as archive:
                members = {info.filename: info for info in archive.infolist()}
                if set(members) != {str(entry.get("stored")) for entry in files}:
                    raise _Problem("damaged")
                total = 0
                for entry in files:
                    stored = str(entry["stored"])
                    parts = safe_parts(stored)
                    info = members[stored]
                    size = int(entry["size"])
                    total += size
                    if info.file_size != size or total > MAX_BYTES:
                        raise _Problem("damaged")
                    target = folder.joinpath("files", *parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, target.open("wb") as sink:
                        shutil.copyfileobj(source, sink)
                    if target.stat().st_size != size or _hash_file(target) != entry["sha256"]:
                        raise _Problem("damaged")
                    out[stored] = target
        except (zipfile.BadZipFile, ArchiveProblem, KeyError, ValueError, TypeError):
            raise _Problem("damaged") from None
        return out

    def restore(self, work_id: str, snapshot_id: str, closed: bool) -> models.CloudWorkOut:
        account = self._require(work_id)
        try:
            self._restore(work_id, account, snapshot_id, closed)
        except _Problem as problem:
            raise AtlasError(f"cloud_{problem.code}", MESSAGES[problem.code], status=409) from None
        except DriveAuthProblem:
            raise AtlasError("cloud_needs_auth", MESSAGES["needs_auth"], status=409) from None
        except (DriveUnreachable, DriveQuotaFull):
            raise AtlasError("cloud_offline", MESSAGES["offline"], status=409) from None
        except DriveProblem:
            raise AtlasError("cloud_error", MESSAGES["error"], status=409) from None
        return self.work_status(work_id)

    def _require(self, work_id: str) -> str:
        self._work(work_id)
        account = self._get(_K_ACCOUNT)
        if not self._connected() or account is None:
            raise AtlasError("cloud_not_connected", MESSAGES["not_connected"], status=409)
        return account

    def _restore(self, work_id: str, account: str, snapshot_id: str, closed: bool) -> Snapshot:
        if not closed:
            raise _Problem("closed")
        work, copy = self._work(work_id)
        if copy is None or not Path(copy.root_path).is_dir():
            raise AtlasError("cloud_folder", "游戏文件夹现在不可用。", status=409)
        root = Path(copy.root_path)
        rules = [rule.model_dump() for rule in self._updater.save_config(work_id).rules]
        if copy.entry_path:
            self._updater.refuse_if_running(root, copy.entry_path)
        drive = self._drive()
        item, _all = self._find(drive, work, snapshot_id)
        if item.manifest.get("schema") != SCHEMA:
            raise _Problem("unknown_schema")
        if item.manifest.get("fingerprint") != fingerprint(rules):
            raise _Problem("config")
        self._staging.mkdir(parents=True, exist_ok=True)
        folder = self._staging / uuid.uuid4().hex
        folder.mkdir()
        try:
            fetched = self._fetch(drive, item, folder)
            # Only after the snapshot is here and good, and before anything local is touched. If
            # this fails, nothing below runs.
            self._updater.protect_saves(work_id, root, rules)
            self._set_state(account, work_id, restoring=snapshot_id)
            self._write(root, rules, item, fetched)
            self._set_state(
                account, work_id, restoring=None, base_snapshot=item.id, base_digest=item.digest
            )
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        return item

    def _write(
        self, root: Path, rules: list[dict[str, str]], item: Snapshot, fetched: dict[str, Path]
    ) -> None:
        """Each file replaced whole, inside the place its rule names. Files a snapshot does not
        list are left alone: a snapshot is not a licence to delete."""
        for entry in item.manifest["files"]:
            index = int(entry["rule"])
            if not 0 <= index < len(rules):
                raise _Problem("config")
            base = self._updater.save_target(rules[index], root)
            target = base
            if not entry.get("is_file_rule"):
                try:
                    target = base.joinpath(*safe_parts(str(entry["relative"])))
                except ArchiveProblem:
                    raise _Problem("damaged") from None
            limit = root if rules[index]["kind"] == "inside" else base
            if not target.resolve().is_relative_to(limit.resolve()):
                raise _Problem("damaged")
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(f".{target.name}.atlas-restore")
            try:
                shutil.copy2(fetched[str(entry["stored"])], partial)
                if _hash_file(partial) != entry["sha256"]:
                    raise _Problem("damaged")
                os.replace(partial, target)
            finally:
                partial.unlink(missing_ok=True)
            if rules[index]["kind"] == "registry":
                self._updater.apply_registry(rules[index])

    def resolve(self, work_id: str, keep: str, closed: bool) -> models.CloudWorkOut:
        """The user's decision on a conflict, written down as a snapshot following every branch, so
        the question is answered on every computer. No branch is deleted: all stay in history."""
        account = self._require(work_id)
        work, _copy = self._work(work_id)
        try:
            drive = self._drive()
            snapshots = self._snapshots(drive, work.source_work_id)
            _state, heads = classify("?", None, None, snapshots)
            parents = [item.id for item in heads]
            if keep == "local":
                return self.backup(work_id, parents)
            item = self._restore(work_id, account, keep, closed)
            manifest = {
                **item.manifest,
                "snapshot": uuid.uuid4().hex,
                "parents": parents,
                "created_at": _now(),
                "device": {"id": self._device(), "name": self._device_name},
            }
            marks = {
                NS_KEY: NAMESPACE,
                "work": work.source_work_id,
                "snapshot": manifest["snapshot"],
                "kind": "commit",
            }
            drive.upload(
                f"{work.source_work_id}-{manifest['snapshot']}.commit.json",
                self._folder(drive),
                marks,
                json.dumps(manifest, ensure_ascii=False).encode(),
                "application/json",
            )
            self._set_state(
                account, work_id, base_snapshot=manifest["snapshot"], base_digest=manifest["digest"]
            )
        except _Problem as problem:
            raise AtlasError(f"cloud_{problem.code}", MESSAGES[problem.code], status=409) from None
        except DriveAuthProblem:
            raise AtlasError("cloud_needs_auth", MESSAGES["needs_auth"], status=409) from None
        except (DriveUnreachable, DriveQuotaFull):
            raise AtlasError("cloud_offline", MESSAGES["offline"], status=409) from None
        except DriveProblem:
            raise AtlasError("cloud_error", MESSAGES["error"], status=409) from None
        return self.work_status(work_id)

    # --- after playing ---

    def game_exited(self, work_id: str, _program: Path | None) -> None:
        """If the user turned this on. Only adds a snapshot, so at worst there is a spare one, and
        the pack step refuses files still changing."""
        if self._get(_K_AUTO_BACKUP) != "1" or not self._connected():
            return
        threading.Thread(
            target=self._backup_when_calm, args=(work_id,), name="cloud-after-play", daemon=True
        ).start()

    def _backup_when_calm(self, work_id: str) -> None:
        self._sleep(self.after_exit_seconds)
        try:
            self.backup(work_id)
        except AtlasError as error:
            logger.info("after-play backup skipped: %s", error.code)
