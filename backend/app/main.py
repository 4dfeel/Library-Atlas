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
from app.api import models
from app.core.config import Settings
from app.core.errors import NOT_READY_MESSAGES, AtlasError
from app.core.security import LocalBoundaryMiddleware, new_csrf_token
from app.db.bootstrap import DatabaseNotReady, open_database
from app.services import library
from app.services.dlsite_auth import DlsiteAuth
from app.services.dlsite_factory import build_dlsite_auth, build_folder_service
from app.services.folders import FolderService

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
            body.login_id, body.password.get_secret_value(), confirm_switch=body.confirm_switch
        )

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
                state.dlsite = dlsite_factory(settings, opened.engine)
                if state.dlsite is not None:
                    state.dlsite.restore()
            except DatabaseNotReady as error:
                state.not_ready_reason = error.reason
                logger.error("database not ready: %s", error.reason)
        yield
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
