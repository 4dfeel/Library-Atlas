"""Wires the DLsite connection to real or test parts. The profile alone decides: no
request, option or environment variable can put stand-ins behind a real library."""

from sqlalchemy import Engine

from app.adapters.dlsite.downloads import PlatformDownloadClient
from app.adapters.dlsite.library import PlayLibraryClient
from app.adapters.dlsite.login_host import BrowserLoginHost
from app.adapters.dlsite.session import PlaySessionChecker
from app.adapters.system.folder_dialog import DialogFolderPicker, ExplorerFolderOpener
from app.core.config import Settings
from app.core.credentials import NAMESPACE, CredentialStoreError, WindowsCredentialStore
from app.services.dlsite_auth import DlsiteAuth
from app.services.dlsite_sync import DlsiteSync
from app.services.downloads import DownloadQueue
from app.services.folders import FolderService


def build_dlsite_auth(settings: Settings, engine: Engine) -> DlsiteAuth | None:
    browser_dir = settings.data_dir / "login-browser"
    if settings.profile == "test":
        from app.testing.fake_dlsite import FakeChecker, FakeControl, FakeLoginHost, FileTestStore

        control = FakeControl(settings.data_dir)
        return DlsiteAuth(
            engine,
            FileTestStore(settings.data_dir, control),
            FakeLoginHost(),
            FakeChecker(control),
            browser_dir,
        )
    try:
        store = WindowsCredentialStore(namespace=f"{NAMESPACE}real/")
    except CredentialStoreError:
        return None
    return DlsiteAuth(engine, store, BrowserLoginHost(), PlaySessionChecker(), browser_dir)


def build_folder_service(settings: Settings, engine: Engine) -> FolderService:
    if settings.profile == "test":
        from app.testing.fake_dlsite import FakeControl, FakeFolderOpener, FakeFolderPicker

        control = FakeControl(settings.data_dir)
        return FolderService(engine, settings, FakeFolderPicker(control), FakeFolderOpener())
    return FolderService(engine, settings, DialogFolderPicker(), ExplorerFolderOpener())


def build_dlsite_sync(settings: Settings, engine: Engine, auth: DlsiteAuth) -> DlsiteSync:
    if settings.profile == "test":
        from app.testing.fake_dlsite import FakeControl, FakeLibraryClient

        control = FakeControl(settings.data_dir)
        return DlsiteSync(engine, auth, lambda _cookies: FakeLibraryClient(control))
    return DlsiteSync(engine, auth, PlayLibraryClient)


def build_download_queue(
    settings: Settings, engine: Engine, auth: DlsiteAuth, folders: FolderService
) -> DownloadQueue:
    if settings.profile == "test":
        import httpx

        from app.testing.fake_dlsite import FakeControl
        from app.testing.fake_download_server import FakeDownloadServer

        control = FakeControl(settings.data_dir)
        # Real sockets and real files; only the platform on the other end is pretend.
        server = FakeDownloadServer(lambda: control.read().get("download", {}))

        def loopback(url: httpx.URL) -> bool:
            return url.host == "127.0.0.1"

        return DownloadQueue(
            engine,
            auth,
            folders,
            lambda cookies: PlatformDownloadClient(
                cookies, entry_url=server.entry_url, allows=loopback
            ),
            wait_seconds=0.05,
            on_shutdown=server.close,
        )
    return DownloadQueue(engine, auth, folders, PlatformDownloadClient)
