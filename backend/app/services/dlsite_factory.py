"""Wires the DLsite connection to real or test parts. The profile alone decides: no
request, option or environment variable can put stand-ins behind a real library."""

from sqlalchemy import Engine

from app.adapters.dlsite.covers import CoverCache
from app.adapters.dlsite.downloads import PlatformDownloadClient
from app.adapters.dlsite.library import PlayLibraryClient
from app.adapters.dlsite.login_host import BrowserLoginHost
from app.adapters.dlsite.product import PublicProductClient
from app.adapters.dlsite.session import PlaySessionChecker
from app.adapters.dlsite.store_page import PublicStorePage
from app.adapters.system.archives import find_seven_zip
from app.adapters.system.folder_dialog import DialogFolderPicker, ExplorerFolderOpener
from app.core.config import Settings
from app.core.credentials import NAMESPACE, CredentialStoreError, WindowsCredentialStore
from app.services.dlsite_auth import DlsiteAuth
from app.services.dlsite_sync import DlsiteSync
from app.services.downloads import DownloadQueue
from app.services.extractions import ExtractionService
from app.services.folders import FolderService
from app.services.gallery import WorkGallery
from app.services.introductions import WorkIntroductions
from app.services.update_checks import UpdateChecker


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


def build_gallery(settings: Settings, engine: Engine, images: CoverCache) -> WorkGallery:
    if settings.profile == "test":
        from app.testing.fake_dlsite import (
            FakeControl,
            FakeProductClient,
            synthetic_image_transport,
        )

        cache = CoverCache(
            settings.data_dir / "cache" / "gallery", transport=synthetic_image_transport
        )
        return WorkGallery(engine, FakeProductClient(FakeControl(settings.data_dir)), cache)
    return WorkGallery(engine, PublicProductClient(), images)


def build_introductions(
    settings: Settings, engine: Engine, images: CoverCache
) -> WorkIntroductions:
    if settings.profile == "test":
        from app.testing.fake_dlsite import (
            FakeControl,
            FakeStorePage,
            synthetic_image_transport,
        )

        cache = CoverCache(
            settings.data_dir / "cache" / "gallery", transport=synthetic_image_transport
        )
        return WorkIntroductions(engine, FakeStorePage(FakeControl(settings.data_dir)), cache)
    return WorkIntroductions(engine, PublicStorePage(), images)


def build_update_checker(settings: Settings, engine: Engine, sync: DlsiteSync) -> UpdateChecker:
    checker = UpdateChecker(engine, sync)
    # A test library has no platform to ask, and tests look for themselves through `tick`.
    if settings.profile != "test":
        checker.start()
    return checker


def build_extraction_service(engine: Engine, folders: FolderService) -> ExtractionService:
    return ExtractionService(engine, folders, find_seven_zip)


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
