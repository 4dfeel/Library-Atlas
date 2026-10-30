"""Application factory: one loopback service for the API and the built frontend."""

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from alembic.runtime.migration import MigrationContext
from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import Engine
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.adapters.dlsite.covers import CoverCache, CoverUnavailable
from app.api import models
from app.core.config import Settings
from app.core.errors import NOT_READY_MESSAGES, AtlasError
from app.core.security import LocalBoundaryMiddleware, new_csrf_token
from app.db.bootstrap import DatabaseNotReady, open_database
from app.services import library
from app.services.dlsite_auth import DlsiteAuth
from app.services.dlsite_factory import (
    build_dlsite_auth,
    build_dlsite_sync,
    build_download_queue,
    build_extraction_service,
    build_folder_service,
    build_gallery,
    build_introductions,
    build_local_copies,
    build_update_checker,
)
from app.services.dlsite_sync import DlsiteSync
from app.services.downloads import DownloadQueue
from app.services.extractions import ExtractionService
from app.services.folders import FolderService
from app.services.gallery import WorkGallery
from app.services.introductions import WorkIntroductions
from app.services.library_scan import LibraryScanner
from app.services.local_copies import LocalCopies
from app.services.update_checks import UpdateChecker

logger = logging.getLogger("atlas")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    ),
}


@dataclass
class ServiceState:
    settings: Settings
    csrf_token: str
    engine: Engine | None = None
    revision: str | None = None
    not_ready_reason: str | None = "starting"
    dlsite: DlsiteAuth | None = None
    folders: FolderService | None = None
    sync: DlsiteSync | None = None
    covers: CoverCache | None = None
    downloads: DownloadQueue | None = None
    extractions: ExtractionService | None = None
    gallery: WorkGallery | None = None
    introductions: WorkIntroductions | None = None
    local_copies: LocalCopies | None = None
    scanner: LibraryScanner | None = None
    updates: UpdateChecker | None = None


def _error_body(
    code: str, message: str, request_id: str | None, *, retryable: bool = False
) -> dict[str, object]:
    return {
        "error": {
            "code": code,
            "message": message,
            "requestId": request_id,
            "retryable": retryable,
        }
    }


def _state(request: Request) -> ServiceState:
    state: ServiceState = request.app.state.service
    return state


def _engine(request: Request) -> Engine:
    state = _state(request)
    if state.engine is None:
        reason = state.not_ready_reason or "starting"
        raise AtlasError(
            "service_not_ready",
            NOT_READY_MESSAGES.get(reason, "服务尚未就绪。"),
            status=503,
            retryable=reason == "starting",
        )
    return state.engine


EngineDep = Annotated[Engine, Depends(_engine)]


def _dlsite(request: Request, _engine: EngineDep) -> DlsiteAuth:
    auth = _state(request).dlsite
    if auth is None:
        raise AtlasError(
            "credential_store_unavailable", "系统凭据存储不可用，无法连接 DLsite。", status=503
        )
    return auth


DlsiteDep = Annotated[DlsiteAuth, Depends(_dlsite)]


def _sync(request: Request, _engine: EngineDep) -> DlsiteSync:
    sync = _state(request).sync
    if sync is None:
        raise AtlasError(
            "credential_store_unavailable", "系统凭据存储不可用，无法同步作品。", status=503
        )
    return sync


SyncDep = Annotated[DlsiteSync, Depends(_sync)]


def _downloads(request: Request, _engine: EngineDep) -> DownloadQueue:
    queue = _state(request).downloads
    if queue is None:
        raise AtlasError(
            "credential_store_unavailable", "系统凭据存储不可用，无法下载。", status=503
        )
    return queue


DownloadsDep = Annotated[DownloadQueue, Depends(_downloads)]


def _extractions(request: Request, _engine: EngineDep) -> ExtractionService:
    service = _state(request).extractions
    assert service is not None  # Built whenever the engine is.
    return service


ExtractionsDep = Annotated[ExtractionService, Depends(_extractions)]


def _gallery(request: Request, _engine: EngineDep) -> WorkGallery:
    service = _state(request).gallery
    assert service is not None  # Built whenever the engine is.
    return service


GalleryDep = Annotated[WorkGallery, Depends(_gallery)]


def _introductions(request: Request, _engine: EngineDep) -> WorkIntroductions:
    service = _state(request).introductions
    assert service is not None  # Built whenever the engine is.
    return service


IntroductionsDep = Annotated[WorkIntroductions, Depends(_introductions)]


def _local_copies(request: Request, _engine: EngineDep) -> LocalCopies:
    service = _state(request).local_copies
    assert service is not None  # Built whenever the engine is.
    return service


CopiesDep = Annotated[LocalCopies, Depends(_local_copies)]


def _scanner(request: Request, _engine: EngineDep) -> LibraryScanner:
    service = _state(request).scanner
    assert service is not None  # Built whenever the engine is.
    return service


ScannerDep = Annotated[LibraryScanner, Depends(_scanner)]


def _updates(request: Request, _engine: EngineDep) -> UpdateChecker:
    checker = _state(request).updates
    if checker is None:
        raise AtlasError(
            "credential_store_unavailable", "系统凭据存储不可用，无法检查更新。", status=503
        )
    return checker


UpdatesDep = Annotated[UpdateChecker, Depends(_updates)]


def _folders(request: Request, _engine: EngineDep) -> FolderService:
    service = _state(request).folders
    assert service is not None  # Built whenever the engine is.
    return service


FoldersDep = Annotated[FolderService, Depends(_folders)]


def _build_api() -> APIRouter:
    api = APIRouter(prefix="/api/v1")

    @api.get("/health")
    def health() -> models.HealthOut:
        return models.HealthOut(version=__version__)

    @api.get("/ready", response_model_exclude_none=True)
    def ready(request: Request, response: Response) -> models.ReadyOut:
        state = _state(request)
        profile = state.settings.profile
        reason = state.not_ready_reason
        if state.engine is not None:
            try:
                with state.engine.connect() as connection:
                    current = MigrationContext.configure(connection).get_current_revision()
                if current == state.revision:
                    return models.ReadyOut(status="ready", profile=profile, schema_revision=current)
                reason = "schema_too_new"
            except SQLAlchemyError:
                reason = "database_unavailable"
        response.status_code = 503
        reason = reason or "starting"
        return models.ReadyOut(
            status="not_ready",
            profile=profile,
            reason=reason,
            message=NOT_READY_MESSAGES.get(reason, "服务尚未就绪。"),
        )

    @api.get("/session")
    def session(request: Request) -> models.SessionOut:
        return models.SessionOut(csrf_token=_state(request).csrf_token)

    @api.get("/works")
    def list_works(
        engine: EngineDep, query: Annotated[models.WorkQuery, Query()]
    ) -> models.WorkPage:
        return library.list_page(engine, query)

    @api.get("/works/{work_id}")
    def get_work(engine: EngineDep, work_id: str) -> models.WorkDetailOut:
        return library.get_detail(engine, work_id)

    @api.patch("/works/{work_id}/personal")
    def patch_personal(
        engine: EngineDep, work_id: str, body: models.PersonalUpdate
    ) -> models.WorkDetailOut:
        return library.update_personal(engine, work_id, body)

    @api.post("/works/{work_id}/favorite/toggle")
    def toggle_favorite(engine: EngineDep, work_id: str) -> models.WorkDetailOut:
        return library.toggle_favorite(engine, work_id)

    @api.get("/dashboard")
    def dashboard(
        engine: EngineDep, query: Annotated[models.DashboardQuery, Query()]
    ) -> models.DashboardOut:
        return library.dashboard(engine, query)

    @api.get("/sources")
    def sources(request: Request, engine: EngineDep) -> models.SourcesOut:
        auth = _state(request).dlsite
        return library.source_status(engine, auth.summary_state() if auth else None)

    @api.get("/sources/dlsite/connection", response_model_exclude_none=True)
    def dlsite_connection(auth: DlsiteDep) -> models.DlsiteConnection:
        return auth.connection()

    @api.post("/sources/dlsite/login", response_model_exclude_none=True)
    def dlsite_login(auth: DlsiteDep, body: models.DlsiteLogin) -> models.DlsiteConnection:
        return auth.start_login(
            body.login_id,
            body.password.get_secret_value(),
            confirm_switch=body.confirm_switch,
            remember=body.remember,
        )

    @api.post("/sources/dlsite/login/saved", response_model_exclude_none=True)
    def dlsite_saved_login(auth: DlsiteDep) -> models.DlsiteConnection:
        return auth.start_saved_login()

    @api.post("/sources/dlsite/saved-login/forget", response_model_exclude_none=True)
    def dlsite_forget_login(auth: DlsiteDep) -> models.DlsiteConnection:
        return auth.forget_saved_login()

    @api.post("/sources/dlsite/login/window", response_model_exclude_none=True)
    def dlsite_window_login(auth: DlsiteDep) -> models.DlsiteConnection:
        return auth.start_window_login()

    @api.post("/sources/dlsite/login/cancel", response_model_exclude_none=True)
    def dlsite_cancel(auth: DlsiteDep) -> models.DlsiteConnection:
        return auth.cancel()

    @api.post("/sources/dlsite/login/reveal", response_model_exclude_none=True)
    def dlsite_reveal(auth: DlsiteDep) -> models.DlsiteConnection:
        return auth.reveal()

    @api.post("/sources/dlsite/verify", response_model_exclude_none=True)
    def dlsite_verify(auth: DlsiteDep) -> models.DlsiteConnection:
        return auth.verify()

    @api.get("/sources/dlsite/sync")
    def sync_status(sync: SyncDep) -> models.SyncStatus:
        return sync.status()

    @api.post("/sources/dlsite/sync")
    def sync_start(sync: SyncDep) -> models.SyncStatus:
        return sync.start()

    @api.post("/sources/dlsite/sync/cancel")
    def sync_cancel(sync: SyncDep) -> models.SyncStatus:
        return sync.cancel()

    @api.get("/works/{work_id}/cover", include_in_schema=False)
    def work_cover(request: Request, engine: EngineDep, work_id: str) -> Response:
        ref = library.cover_reference(engine, work_id)
        covers = _state(request).covers
        if not ref or covers is None:
            raise AtlasError("cover_unavailable", "没有封面。", status=404)
        try:
            path, content_type = covers.get(ref)
        except CoverUnavailable:
            raise AtlasError("cover_unavailable", "封面暂时无法获取。", status=404) from None
        return FileResponse(
            path, media_type=content_type, headers={"Cache-Control": "private, max-age=604800"}
        )

    # POST, though it changes nothing here: it spends the user's session on the platform.
    @api.post("/works/{work_id}/download-plan")
    def download_plan(queue: DownloadsDep, work_id: str) -> models.DownloadPlanOut:
        return queue.plan(work_id)

    @api.get("/downloads")
    def list_downloads(queue: DownloadsDep, work_id: str | None = None) -> models.DownloadsOut:
        return queue.tasks(work_id)

    @api.post("/downloads", status_code=202)
    def create_download(queue: DownloadsDep, body: models.DownloadCreate) -> models.DownloadsOut:
        return queue.create(body)

    @api.post("/downloads/clear")
    def clear_downloads(queue: DownloadsDep) -> models.DownloadsOut:
        return queue.clear_finished()

    @api.post("/downloads/{task_id}/cancel")
    def cancel_download(queue: DownloadsDep, task_id: str) -> models.DownloadTaskOut:
        return queue.cancel(task_id)

    @api.post("/downloads/{task_id}/pause")
    def pause_download(queue: DownloadsDep, task_id: str) -> models.DownloadTaskOut:
        return queue.pause(task_id)

    @api.post("/downloads/{task_id}/retry")
    def retry_download(queue: DownloadsDep, task_id: str) -> models.DownloadTaskOut:
        return queue.retry(task_id)

    @api.post("/downloads/{task_id}/open-folder")
    def open_download_folder(queue: DownloadsDep, task_id: str) -> models.DownloadTaskOut:
        return queue.open_folder(task_id)

    @api.get("/works/{work_id}/gallery")
    def work_gallery(service: GalleryDep, work_id: str) -> models.GalleryOut:
        return service.gallery(work_id)

    @api.get("/works/{work_id}/gallery/{index}", include_in_schema=False)
    def work_gallery_image(service: GalleryDep, work_id: str, index: int) -> Response:
        path, content_type = service.image(work_id, index)
        return FileResponse(
            path, media_type=content_type, headers={"Cache-Control": "private, max-age=604800"}
        )

    @api.get("/works/{work_id}/introduction")
    def work_introduction(service: IntroductionsDep, work_id: str) -> models.IntroOut:
        return service.introduction(work_id)

    @api.post("/works/{work_id}/introduction/refresh")
    def refresh_introduction(service: IntroductionsDep, work_id: str) -> models.IntroOut:
        return service.introduction(work_id, refresh=True)

    @api.get("/works/{work_id}/intro-image/{index}", include_in_schema=False)
    def work_intro_image(service: IntroductionsDep, work_id: str, index: int) -> Response:
        path, content_type = service.image(work_id, index)
        return FileResponse(
            path, media_type=content_type, headers={"Cache-Control": "private, max-age=604800"}
        )

    @api.get("/works/{work_id}/local-copies")
    def list_copies(service: CopiesDep, work_id: str) -> models.LocalCopiesOut:
        return service.copies(work_id)

    @api.post("/works/{work_id}/local-copies")
    def add_copy(
        service: CopiesDep, work_id: str, body: models.LocalCopyIn
    ) -> models.LocalCopiesOut:
        return service.add(work_id, body)

    @api.post("/works/{work_id}/local-copies/preview")
    def preview_copy(
        service: CopiesDep, work_id: str, body: models.CopyPreviewIn
    ) -> models.CopyPreviewOut:
        return service.preview(body.path)

    @api.post("/local-copies/choose-folder")
    def choose_copy_folder(service: CopiesDep) -> models.ChosenFolderOut:
        return service.choose_folder()

    @api.patch("/local-copies/{copy_id}")
    def update_copy(
        service: CopiesDep, copy_id: str, body: models.LocalCopyUpdate
    ) -> models.LocalCopyOut:
        return service.update_copy(copy_id, body)

    @api.delete("/local-copies/{copy_id}")
    def remove_copy(service: CopiesDep, copy_id: str) -> models.LocalCopiesOut:
        return service.remove(copy_id)

    @api.post("/local-copies/{copy_id}/default")
    def default_copy(service: CopiesDep, copy_id: str) -> models.LocalCopiesOut:
        return service.set_default(copy_id)

    @api.post("/local-copies/{copy_id}/open")
    def open_copy(service: CopiesDep, copy_id: str) -> models.LocalCopyOut:
        return service.open_folder(copy_id)

    @api.post("/local-copies/{copy_id}/launch")
    def launch_copy(service: CopiesDep, copy_id: str) -> models.LaunchOut:
        return service.launch(copy_id)

    @api.get("/library-scan")
    def scan_status(service: ScannerDep) -> models.ScanStatus:
        return service.status()

    @api.get("/library-scan/items")
    def scan_items(
        service: ScannerDep,
        state: models.ScanItemState | None = None,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> models.ScanItemsOut:
        return service.items(state, offset, limit)

    @api.post("/library-scan/start")
    def scan_start(service: ScannerDep, body: models.ScanStart) -> models.ScanStatus:
        return service.start(body)

    @api.post("/library-scan/cancel")
    def scan_cancel(service: ScannerDep) -> models.ScanStatus:
        return service.cancel()

    @api.post("/library-scan/import")
    def scan_import(service: ScannerDep, body: models.ScanImport) -> models.ScanImportOut:
        return service.import_matches(body)

    @api.post("/library-scan/undo/{batch_id}")
    def scan_undo(service: ScannerDep, batch_id: str) -> models.ScanImportOut:
        return service.undo(batch_id)

    @api.post("/library-scan/items/{item_id}/link")
    def scan_link(service: ScannerDep, item_id: str, body: models.ScanLink) -> models.ScanItemsOut:
        return service.link_item(item_id, body.work_id)

    @api.post("/library-scan/items/{item_id}/ignore")
    def scan_ignore(service: ScannerDep, item_id: str) -> models.ScanItemsOut:
        return service.ignore_item(item_id)

    @api.get("/settings/updates")
    def update_settings(checker: UpdatesDep) -> models.UpdateSettings:
        return checker.status()

    @api.put("/settings/updates")
    def set_update_settings(
        checker: UpdatesDep, body: models.UpdateSettingsIn
    ) -> models.UpdateSettings:
        return checker.set_auto(body.auto_check)

    @api.get("/extractions")
    def list_extractions(service: ExtractionsDep) -> models.ExtractionsOut:
        return service.tasks()

    @api.post("/extractions", status_code=202)
    def create_extraction(
        service: ExtractionsDep, body: models.ExtractCreate
    ) -> models.ExtractionsOut:
        return service.start(body.work_id, again=body.again)

    @api.post("/extractions/clear")
    def clear_extractions(service: ExtractionsDep) -> models.ExtractionsOut:
        return service.clear_finished()

    @api.post("/extractions/{task_id}/cancel")
    def cancel_extraction(service: ExtractionsDep, task_id: str) -> models.ExtractTaskOut:
        return service.cancel(task_id)

    @api.post("/extractions/{task_id}/retry")
    def retry_extraction(service: ExtractionsDep, task_id: str) -> models.ExtractTaskOut:
        return service.retry(task_id)

    @api.post("/extractions/{task_id}/open-folder")
    def open_extraction_folder(service: ExtractionsDep, task_id: str) -> models.ExtractTaskOut:
        return service.open_folder(task_id)

    @api.get("/settings/folders")
    def get_folders(service: FoldersDep) -> models.FoldersOut:
        return service.folders()

    @api.put("/settings/folders/{kind}")
    def set_folder(
        service: FoldersDep, kind: models.FolderKind, body: models.FolderUpdate
    ) -> models.FoldersOut:
        return service.set_folder(kind, body.path)

    @api.post("/settings/folders/{kind}/pick")
    def pick_folder(service: FoldersDep, kind: models.FolderKind) -> models.FoldersOut:
        return service.pick(kind)

    @api.post("/settings/folders/{kind}/open")
    def open_folder(service: FoldersDep, kind: models.FolderKind) -> models.FoldersOut:
        return service.open_folder(kind)

    @api.post("/sources/dlsite/disconnect", response_model_exclude_none=True)
    def dlsite_disconnect(auth: DlsiteDep) -> models.DlsiteConnection:
        return auth.disconnect()

    @api.api_route(
        "/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False
    )
    def unknown_api(rest: str) -> None:
        raise AtlasError("not_found", "接口不存在。", status=404)

    return api


def _static_response(static_dir: Path | None, path: str) -> Response:
    """Files inside the build, otherwise the SPA shell. Nothing outside the build is served."""
    if static_dir is None:
        return JSONResponse(
            _error_body("frontend_not_built", "前端尚未构建，请先运行 npm run build。", None),
            status_code=503,
        )
    root = static_dir.resolve()
    candidate = (root / path).resolve()
    if path and candidate.is_relative_to(root) and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})


def create_app(
    settings: Settings,
    *,
    open_db: bool = True,
    dlsite_factory: Callable[[Settings, Engine], DlsiteAuth | None] = build_dlsite_auth,
    dlsite_sync_factory: Callable[[Settings, Engine, DlsiteAuth], DlsiteSync] = build_dlsite_sync,
) -> FastAPI:
    state = ServiceState(settings=settings, csrf_token=new_csrf_token())

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if open_db:
            try:
                opened = open_database(
                    settings.database_path, settings.backup_dir, settings.profile
                )
                state.engine, state.revision = opened.engine, opened.revision
                state.not_ready_reason = None
                state.folders = build_folder_service(settings, opened.engine)
                state.extractions = build_extraction_service(opened.engine, state.folders)
                state.extractions.recover()
                state.local_copies = build_local_copies(settings, opened.engine, state.folders)
                state.extractions.on_result = state.local_copies.record_unpacked
                # A test library is never shown the real drives, so no test can read them.
                state.scanner = (
                    LibraryScanner(opened.engine, state.local_copies, lambda: [])
                    if settings.profile == "test"
                    else LibraryScanner(opened.engine, state.local_copies)
                )
                state.scanner.recover()
                state.dlsite = dlsite_factory(settings, opened.engine)
                state.covers = CoverCache(settings.data_dir / "cache" / "covers")
                state.gallery = build_gallery(settings, opened.engine, state.covers)
                state.introductions = build_introductions(settings, opened.engine, state.covers)
                if state.dlsite is not None:
                    state.sync = dlsite_sync_factory(settings, opened.engine, state.dlsite)
                    state.sync.recover()
                    assert state.folders is not None  # Built just above.
                    state.downloads = build_download_queue(
                        settings, opened.engine, state.dlsite, state.folders
                    )
                    state.downloads.recover()
                    state.downloads.on_flow_finished = state.extractions.flow_finished
                    state.updates = build_update_checker(settings, opened.engine, state.sync)
                    state.dlsite.restore()
            except DatabaseNotReady as error:
                state.not_ready_reason = error.reason
                logger.error("database not ready: %s", error.reason)
        yield
        if state.scanner is not None:
            state.scanner.shutdown()
        if state.updates is not None:
            state.updates.shutdown()
        if state.extractions is not None:
            state.extractions.shutdown()
        if state.downloads is not None:
            state.downloads.shutdown()
        if state.sync is not None:
            state.sync.shutdown()
        if state.dlsite is not None:
            state.dlsite.shutdown()
        if state.engine is not None:
            state.engine.dispose()

    app = FastAPI(
        title="Library Atlas",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.service = state

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.request_id = uuid.uuid4().hex
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        # The route template only: no query strings, titles, IDs or paths in the log.
        route = request.scope.get("route")
        logger.info(
            "%s %s %s %.0fms",
            request.method,
            getattr(route, "path", "(static)"),
            response.status_code,
            (time.perf_counter() - started) * 1000,
        )
        return response

    def request_id(request: Request) -> str | None:
        return getattr(request.state, "request_id", None)

    @app.exception_handler(AtlasError)
    async def on_atlas_error(request: Request, error: AtlasError) -> JSONResponse:
        return JSONResponse(
            _error_body(error.code, error.message, request_id(request), retryable=error.retryable),
            status_code=error.status,
        )

    @app.exception_handler(RequestValidationError)
    async def on_invalid_request(request: Request, _error: RequestValidationError) -> JSONResponse:
        # The details echo user input, so they stay out of the response and the log.
        return JSONResponse(
            _error_body("invalid_request", "请求内容无效。", request_id(request)), status_code=422
        )

    @app.exception_handler(StarletteHTTPException)
    async def on_http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            _error_body("http_error", "请求无法处理。", request_id(request)),
            status_code=error.status_code,
        )

    @app.exception_handler(DBAPIError)
    async def on_database_error(request: Request, error: DBAPIError) -> JSONResponse:
        logger.error("database error %s request=%s", type(error.orig).__name__, request_id(request))
        return JSONResponse(
            _error_body(
                "database_unavailable",
                "资料库暂时无法访问，修改尚未保存，请重试。",
                request_id(request),
                retryable=True,
            ),
            status_code=503,
        )

    @app.exception_handler(Exception)
    async def on_unexpected(request: Request, error: Exception) -> JSONResponse:
        logger.error("unexpected %s request=%s", type(error).__name__, request_id(request))
        return JSONResponse(
            _error_body(
                "internal_error", "服务遇到意外错误。", request_id(request), retryable=True
            ),
            status_code=500,
        )

    app.include_router(_build_api())

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str) -> Response:
        return _static_response(settings.static_dir, path)

    app.add_middleware(LocalBoundaryMiddleware, settings=settings, csrf_token=state.csrf_token)
    return app
