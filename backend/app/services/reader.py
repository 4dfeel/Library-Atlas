"""Books inside a work's linked folder, their pages, and how far the user has read.

Each folder that directly holds images is its own book, and each ZIP, CBZ or PDF is another: nested
folders are never run together. Archives are read in place, one bounded member at a time, and never
unpacked to disk. A page's ID covers its content, so a replaced file is not mistaken for the page
the user left off on.
"""

import hashlib
import os
import threading
import uuid
import zipfile
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import Engine, Row, delete, select
from sqlalchemy.dialects.sqlite import insert

from app.adapters.system.archives import ArchiveProblem, open_zip
from app.api import models
from app.core.errors import AtlasError
from app.db.engine import writing
from app.db.schema import reader_bookmarks, reading_progress
from app.domain.image_header import HEAD_BYTES, acceptable, read_header
from app.repositories.works import get_ordinary_work
from app.services.local_media import IMAGE_TYPES, LocalMedia, MediaFile, path_key

ARCHIVE_SUFFIXES = {".zip", ".cbz"}
PDF_SUFFIX = ".pdf"
# Shown, so a work is not called empty, with the reason it cannot be opened here.
UNSUPPORTED = {
    ".rar": "RAR 还不能直接阅读，可以先解压",
    ".cbr": "CBR 还不能直接阅读，可以先解压",
    ".7z": "7z 还不能直接阅读，可以先解压",
    ".cb7": "CB7 还不能直接阅读，可以先解压",
    ".epub": "EPUB 还不支持",
    ".mobi": "MOBI 还不支持",
    ".azw3": "AZW3 还不支持",
    ".dlst": "平台专用格式，请用官方阅读器",
}
MAX_PAGE_BYTES = 256 * 1024 * 1024
MAX_MEMBERS = 50_000
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024 * 1024
# Images barely compress. Far beyond this, a member is built to blow up when read.
MAX_RATIO = 200
_ARCHIVE_CACHE = 8
_ARCHIVE_READS = 4


@dataclass(frozen=True)
class Book:
    id: str
    kind: models.BookKind
    name: str
    group: str
    relative: str
    files: tuple[MediaFile, ...]


@dataclass(frozen=True)
class ArchivePage:
    id: str
    member: str
    name: str
    section: str


@dataclass(frozen=True)
class ArchiveListing:
    pages: tuple[ArchivePage, ...]
    skipped: int
    encrypted: bool


@dataclass(frozen=True)
class PagePayload:
    media_type: str
    path: Path | None = None
    content: bytes | None = None


def _digest(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()[:32]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _unreadable(message: str = "这一页无法显示。") -> AtlasError:
    return AtlasError("page_unreadable", message, status=415)


def _safe_member(name: str) -> bool:
    if "\\" in name or ":" in name or name.startswith("/"):
        return False
    return ".." not in PurePosixPath(name).parts


def list_archive(book_id: str, path: Path) -> ArchiveListing:
    """Only reads the archive's index. What it refuses is counted, so nothing vanishes silently."""
    try:
        with open_zip(path) as archive:
            members = archive.infolist()
    except (ArchiveProblem, OSError):
        raise AtlasError(
            "book_unreadable", "这个压缩包无法读取，可能已损坏。", status=422
        ) from None
    if len(members) > MAX_MEMBERS:
        raise AtlasError("book_unreadable", "这个压缩包文件太多，无法阅读。", status=422)
    if sum(member.file_size for member in members) > MAX_ARCHIVE_BYTES:
        raise AtlasError("book_unreadable", "这个压缩包太大，无法直接阅读。", status=422)
    pages = []
    skipped = 0
    encrypted = False
    for member in members:
        if member.is_dir():
            continue
        suffix = os.path.splitext(member.filename)[1].lower()
        if suffix not in IMAGE_TYPES:
            continue
        if member.flag_bits & 0x1:
            encrypted = True
            skipped += 1
            continue
        oversized = member.file_size > MAX_PAGE_BYTES or (
            member.file_size > member.compress_size * MAX_RATIO + 1024 * 1024
        )
        if oversized or not _safe_member(member.filename):
            skipped += 1
            continue
        section, _, name = member.filename.rpartition("/")
        pages.append(
            ArchivePage(
                _digest(book_id, member.filename, str(member.CRC), str(member.file_size)),
                member.filename,
                name,
                section,
            )
        )
    pages.sort(key=lambda page: path_key(page.member))
    return ArchiveListing(tuple(pages), skipped, encrypted)


class Reader:
    def __init__(self, engine: Engine, media: LocalMedia) -> None:
        self._engine = engine
        self._media = media
        self._lock = threading.Lock()
        self._archives: OrderedDict[tuple[str, str], ArchiveListing] = OrderedDict()
        self._reads = threading.BoundedSemaphore(_ARCHIVE_READS)

    # --- finding books ---

    def _found(self, copy_id: str, root: Path) -> tuple[list[Book], list[MediaFile], bool]:
        suffixes = {*IMAGE_TYPES, *ARCHIVE_SUFFIXES, PDF_SUFFIX, *UNSUPPORTED}
        files, complete = self._media.files(copy_id, root, suffixes)
        folders: dict[str, list[MediaFile]] = {}
        books: list[Book] = []
        unsupported: list[MediaFile] = []
        for item in files:
            folder, _, name = item.relative.rpartition("/")
            if item.suffix in IMAGE_TYPES:
                folders.setdefault(folder, []).append(item)
            elif item.suffix in UNSUPPORTED:
                unsupported.append(item)
            else:
                kind: models.BookKind = "pdf" if item.suffix == PDF_SUFFIX else "archive"
                book_id = _digest(copy_id, kind, item.relative.casefold())
                books.append(Book(book_id, kind, name, folder, item.relative, (item,)))
        for folder, images in folders.items():
            parent, _, name = folder.rpartition("/")
            book_id = _digest(copy_id, "images", folder.casefold())
            books.append(Book(book_id, "images", name or "根目录", parent, folder, tuple(images)))
        books.sort(key=lambda book: path_key(book.relative))
        return books, unsupported, complete

    def _book(self, copy_id: str, book_id: str) -> tuple[Row[Any], Book]:
        row = self._media.ordinary_copy(copy_id)
        root = Path(row.root_path)
        if not root.is_dir():
            raise AtlasError("media_offline", "这个文件夹现在不可用。", status=404)
        books, _unsupported, _complete = self._found(copy_id, root)
        match = next((book for book in books if book.id == book_id), None)
        if match is None:
            raise AtlasError("media_not_found", "找不到这本。", status=404)
        return row, match

    def books(self, work_id: str) -> models.BooksOut:
        row = self._media.copy_for(work_id, None)
        if row is None:
            return models.BooksOut(state="no_copy", books=[], unsupported=[])
        root = Path(row.root_path)
        if not root.is_dir():
            return models.BooksOut(state="offline", copy_id=row.id, books=[], unsupported=[])
        books, unsupported, complete = self._found(row.id, root)
        with self._engine.connect() as connection:
            progress = {
                item.book_id: item
                for item in connection.execute(
                    select(reading_progress).where(reading_progress.c.work_id == work_id)
                )
            }
        latest: tuple[str, str] | None = None
        results = []
        for book in books:
            saved = progress.get(book.id)
            if saved is not None and (latest is None or saved.updated_at > latest[1]):
                latest = (book.id, saved.updated_at)
            results.append(
                models.BookOut(
                    id=book.id,
                    kind=book.kind,
                    name=book.name,
                    group=book.group,
                    page_count=(
                        len(book.files)
                        if book.kind == "images"
                        else (saved.page_count if saved is not None else None)
                    ),
                    page_index=saved.page_index if saved is not None else None,
                    read_state=saved.read_state if saved is not None else "unread",
                )
            )
        return models.BooksOut(
            state="ready" if results or unsupported else "empty",
            copy_id=row.id,
            books=results,
            unsupported=[
                models.UnsupportedBook(name=item.relative, reason=UNSUPPORTED[item.suffix])
                for item in unsupported
            ],
            complete=complete,
            last_book_id=latest[0] if latest else None,
        )

    # --- pages ---

    def _listing(self, book: Book) -> ArchiveListing:
        key = (book.id, book.files[0].stamp)
        with self._lock:
            cached = self._archives.get(key)
            if cached is not None:
                self._archives.move_to_end(key)
                return cached
        listing = list_archive(book.id, book.files[0].path)
        with self._lock:
            self._archives[key] = listing
            while len(self._archives) > _ARCHIVE_CACHE:
                self._archives.popitem(last=False)
        return listing

    @staticmethod
    def _image_page_id(item: MediaFile) -> str:
        return _digest(item.id, item.stamp)

    def pages(self, copy_id: str, book_id: str) -> models.BookPagesOut:
        row, book = self._book(copy_id, book_id)
        skipped = 0
        encrypted = False
        if book.kind == "images":
            pages = [
                models.PageOut(
                    id=self._image_page_id(item),
                    name=item.relative.rpartition("/")[2],
                    section="",
                )
                for item in book.files
            ]
        elif book.kind == "archive":
            listing = self._listing(book)
            skipped, encrypted = listing.skipped, listing.encrypted
            pages = [
                models.PageOut(id=page.id, name=page.name, section=page.section)
                for page in listing.pages
            ]
        else:
            self._check_pdf(book)
            pages = []
        with self._engine.connect() as connection:
            saved = connection.execute(
                select(reading_progress).where(reading_progress.c.book_id == book_id)
            ).first()
        return models.BookPagesOut(
            id=book.id,
            kind=book.kind,
            name=book.name,
            version=_digest(book.files[0].stamp)[:12],
            pages=pages,
            skipped=skipped,
            encrypted=encrypted,
            page_id=saved.page_id if saved is not None else None,
            page_index=saved.page_index if saved is not None else None,
            read_state=saved.read_state if saved is not None else "unread",
            work_id=row.work_id,
        )

    def page(self, copy_id: str, book_id: str, page_id: str) -> PagePayload:
        row, book = self._book(copy_id, book_id)
        if book.kind == "images":
            item = next(
                (entry for entry in book.files if self._image_page_id(entry) == page_id), None
            )
            if item is None:
                raise AtlasError("media_not_found", "这一页已经不在了。", status=404)
            return self._image_file(row, item)
        if book.kind == "archive":
            page = next((entry for entry in self._listing(book).pages if entry.id == page_id), None)
            if page is None:
                raise AtlasError("media_not_found", "这一页已经不在了。", status=404)
            return self._archive_member(book, page)
        raise AtlasError("media_not_found", "这一页已经不在了。", status=404)

    def _image_file(self, row: Row[Any], item: MediaFile) -> PagePayload:
        root = Path(row.root_path).resolve()
        try:
            if not item.path.is_file() or not item.path.resolve().is_relative_to(root):
                raise AtlasError("media_not_found", "这一页已经不在了。", status=404)
            if item.path.stat().st_size > MAX_PAGE_BYTES:
                raise _unreadable("这一页文件太大，无法显示。")
            with item.path.open("rb") as stream:
                head = stream.read(HEAD_BYTES)
        except OSError:
            raise AtlasError("media_not_found", "这一页现在读不到。", status=404) from None
        header = read_header(head)
        if header is None or not acceptable(header):
            raise _unreadable()
        return PagePayload(header.media_type, path=item.path)

    def _archive_member(self, book: Book, page: ArchivePage) -> PagePayload:
        with self._reads:
            try:
                with (
                    open_zip(book.files[0].path) as archive,
                    archive.open(page.member) as stream,
                ):
                    # The index can lie about the size; this cannot be made to read more.
                    content = stream.read(MAX_PAGE_BYTES + 1)
            except (ArchiveProblem, OSError, KeyError, zipfile.BadZipFile, RuntimeError):
                raise _unreadable() from None
        if len(content) > MAX_PAGE_BYTES:
            raise _unreadable("这一页文件太大，无法显示。")
        header = read_header(content[:HEAD_BYTES])
        if header is None or not acceptable(header):
            raise _unreadable()
        return PagePayload(header.media_type, content=content)

    @staticmethod
    def _check_pdf(book: Book) -> None:
        try:
            with book.files[0].path.open("rb") as stream:
                head = stream.read(1024)
        except OSError:
            raise AtlasError("media_not_found", "这个文件现在读不到。", status=404) from None
        if b"%PDF-" not in head:
            raise AtlasError("book_unreadable", "这个 PDF 无法读取，可能已损坏。", status=422)

    def pdf(self, copy_id: str, book_id: str) -> Path:
        row, book = self._book(copy_id, book_id)
        if book.kind != "pdf":
            raise AtlasError("media_not_found", "找不到这本。", status=404)
        path = book.files[0].path
        if not path.is_file() or not path.resolve().is_relative_to(Path(row.root_path).resolve()):
            raise AtlasError("media_not_found", "这个文件已经不在了。", status=404)
        self._check_pdf(book)
        return path

    # --- where the user is ---

    def save_position(self, body: models.ReadingPositionIn) -> None:
        row, _book = self._book(body.copy_id, body.book_id)
        values: dict[str, Any] = {
            "work_id": row.work_id,
            "page_id": body.page_id,
            "page_index": body.page_index,
            "page_count": body.page_count,
            "updated_at": _now(),
        }
        update = dict(values)
        if body.finished:
            update["read_state"] = "read"
        with writing(self._engine).begin() as connection:
            connection.execute(
                insert(reading_progress)
                .values(
                    book_id=body.book_id,
                    read_state="read" if body.finished else "reading",
                    **values,
                )
                .on_conflict_do_update(index_elements=[reading_progress.c.book_id], set_=update)
            )

    def set_read(self, body: models.ReadStateIn) -> None:
        """By hand, either way. Opening a book never counts."""
        row, _book = self._book(body.copy_id, body.book_id)
        state = "read" if body.read else "unread"
        with writing(self._engine).begin() as connection:
            connection.execute(
                insert(reading_progress)
                .values(
                    book_id=body.book_id,
                    work_id=row.work_id,
                    page_id=None,
                    page_index=0,
                    page_count=None,
                    read_state=state,
                    updated_at=_now(),
                )
                .on_conflict_do_update(
                    index_elements=[reading_progress.c.book_id],
                    set_={"read_state": state, "updated_at": _now()},
                )
            )

    # --- bookmarks ---

    def bookmarks(self, copy_id: str, book_id: str) -> models.ReaderBookmarksOut:
        self._book(copy_id, book_id)
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(reader_bookmarks)
                .where(reader_bookmarks.c.book_id == book_id)
                .order_by(reader_bookmarks.c.page_index, reader_bookmarks.c.created_at)
            ).all()
        return models.ReaderBookmarksOut(
            bookmarks=[
                models.ReaderBookmark(id=row.id, page_id=row.page_id, page_index=row.page_index)
                for row in rows
            ]
        )

    def add_bookmark(self, body: models.ReaderBookmarkIn) -> models.ReaderBookmarksOut:
        row, _book = self._book(body.copy_id, body.book_id)
        with writing(self._engine).begin() as connection:
            connection.execute(
                reader_bookmarks.insert().values(
                    id=uuid.uuid4().hex,
                    work_id=row.work_id,
                    book_id=body.book_id,
                    page_id=body.page_id,
                    page_index=body.page_index,
                    created_at=_now(),
                )
            )
        return self.bookmarks(body.copy_id, body.book_id)

    def remove_bookmark(self, bookmark_id: str) -> None:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(reader_bookmarks).where(reader_bookmarks.c.id == bookmark_id)
            ).first()
            if row is None:
                return
            get_ordinary_work(connection, row.work_id)
        with writing(self._engine).begin() as connection:
            connection.execute(delete(reader_bookmarks).where(reader_bookmarks.c.id == bookmark_id))
