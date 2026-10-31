import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
  type WheelEvent,
} from 'react';
import { createPortal } from 'react-dom';
import type { PDFDocumentProxy } from 'pdfjs-dist';
import {
  ArrowLeftRight,
  Bookmark,
  BookmarkCheck,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Maximize,
  Minimize,
  RotateCcw,
  Trash2,
  X,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  useBookPages,
  useReaderBookmarks,
  useReaderActions,
  type ReaderBook,
  type ReaderPage,
} from '@/lib/data';
import { drawPage, openPdf } from './pdf-document';
import {
  onScreen,
  spreadAt,
  stepForSide,
  turn,
  type ReaderDirection,
  type ReaderMode,
} from './spreads';

type Fit = 'page' | 'width' | 'zoom';

interface Choices {
  mode: ReaderMode;
  direction: ReaderDirection;
}

const CHOICES_KEY = 'atlas.reader.choices';
const ZOOM_STEP = 25;
const PRELOAD = 2;
// One notch of a wheel is 100 or less, far less on a high-DPI screen; a touchpad's many small
// amounts add up to a turn.
const WHEEL_TURN = 20;
const WHEEL_LINE = 40;
// A long flick must not run through the book, or carry on past the end of a scroll.
const WHEEL_REST_MS = 220;

function loadChoices(bookId: string): Choices {
  const fallback: Choices = { mode: 'single', direction: 'ltr' };
  try {
    const saved = JSON.parse(localStorage.getItem(CHOICES_KEY) ?? '{}') as Record<string, Choices>;
    return saved[bookId] ?? fallback;
  } catch {
    return fallback;
  }
}

function saveChoices(bookId: string, choices: Choices) {
  try {
    const saved = JSON.parse(localStorage.getItem(CHOICES_KEY) ?? '{}') as Record<string, Choices>;
    localStorage.setItem(CHOICES_KEY, JSON.stringify({ ...saved, [bookId]: choices }));
  } catch {
    // Only a convenience: the book still opens with the defaults.
  }
}

function pageUrl(copyId: string, bookId: string, pageId: string) {
  return `/api/v1/media/pages/${encodeURIComponent(copyId)}/${encodeURIComponent(bookId)}/${encodeURIComponent(pageId)}`;
}

/** A page that could not be shown keeps its place in the book and can be tried again. */
function PageProblem({ number, onRetry }: { number: number; onRetry: () => void }) {
  return (
    <div className="reader-problem" role="alert" data-testid="reader-page-problem">
      <CircleAlert size={18} />
      <span>第 {number} 页无法显示</span>
      <Button
        variant="ghost"
        size="sm"
        onClick={(event) => {
          event.stopPropagation();
          onRetry();
        }}
      >
        <RotateCcw size={13} />
        重试
      </Button>
    </div>
  );
}

function ImagePage({ url, number, lazy }: { url: string; number: number; lazy: boolean }) {
  const [attempt, setAttempt] = useState(0);
  const [failedAt, setFailedAt] = useState<number | null>(null);
  if (failedAt === attempt)
    return <PageProblem number={number} onRetry={() => setAttempt(attempt + 1)} />;
  return (
    <img
      key={attempt}
      src={attempt ? `${url}?retry=${attempt}` : url}
      alt={`第 ${number} 页`}
      className="reader-page"
      data-page={number}
      draggable={false}
      decoding="async"
      loading={lazy ? 'lazy' : 'eager'}
      onError={() => setFailedAt(attempt)}
    />
  );
}

function PdfPage({ document, number }: { document: PDFDocumentProxy; number: number }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [attempt, setAttempt] = useState(0);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const target = canvas.current;
    if (!target) return undefined;
    const wanted = (target.parentElement?.clientWidth ?? 1000) * window.devicePixelRatio;
    return drawPage(document, number, target, wanted, (error) => {
      if (error) setFailed(true);
    });
  }, [document, number, attempt]);
  if (failed)
    return (
      <PageProblem
        number={number}
        onRetry={() => {
          setFailed(false);
          setAttempt(attempt + 1);
        }}
      />
    );
  return (
    <canvas
      ref={canvas}
      className="reader-page"
      data-page={number}
      aria-label={`第 ${number} 页`}
    />
  );
}

/** Draws a PDF page only once it is near the screen, so a long book is not drawn all at once. */
function NearScreen({ children }: { children: React.ReactNode }) {
  const holder = useRef<HTMLDivElement>(null);
  const [near, setNear] = useState(false);
  useEffect(() => {
    if (!holder.current) return undefined;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) setNear(true);
      },
      { rootMargin: '100% 0px' },
    );
    observer.observe(holder.current);
    return () => observer.disconnect();
  }, []);
  return (
    <div ref={holder} className="reader-near">
      {near && children}
    </div>
  );
}

export function ReaderView({
  copyId,
  book,
  onClose,
}: {
  copyId: string;
  book: ReaderBook;
  onClose: () => void;
}) {
  const { data, error, retry } = useBookPages(copyId, book.id);
  const [pdf, setPdf] = useState<{ document: PDFDocumentProxy; count: number } | null>(null);
  const [pdfFailed, setPdfFailed] = useState(false);
  useEffect(() => {
    if (book.kind !== 'pdf') return undefined;
    let gone = false;
    let destroy: (() => void) | undefined;
    openPdf(`/api/v1/media/books/${encodeURIComponent(copyId)}/${encodeURIComponent(book.id)}/file`)
      .then((task) => {
        destroy = () => void task.destroy();
        if (gone) destroy();
        return task.promise;
      })
      .then((document) => {
        if (!gone) setPdf({ document, count: document.numPages });
      })
      .catch(() => {
        if (!gone) setPdfFailed(true);
      });
    return () => {
      gone = true;
      destroy?.();
    };
  }, [book.id, book.kind, copyId]);

  const pages: ReaderPage[] = useMemo(() => {
    if (!data) return [];
    if (data.kind !== 'pdf') return data.pages;
    return Array.from({ length: pdf?.count ?? 0 }, (_, index) => ({
      id: `${data.version}-${index + 1}`,
      name: `${index + 1}`,
      section: '',
    }));
  }, [data, pdf]);

  const ready = data && (data.kind !== 'pdf' || pdf);
  return createPortal(
    ready ? (
      <ReaderSurface
        key={book.id}
        copyId={copyId}
        book={book}
        pages={pages}
        savedPageId={data.pageId}
        readState={data.readState}
        skipped={data.skipped}
        encrypted={data.encrypted}
        pdf={pdf?.document ?? null}
        onClose={onClose}
      />
    ) : (
      <div className="reader" role="dialog" aria-modal="true" aria-label={book.name}>
        <div className="reader-bar">
          <span className="reader-title">{book.name}</span>
          <Button variant="ghost" size="icon" aria-label="关闭阅读器" onClick={onClose}>
            <X size={16} />
          </Button>
        </div>
        <div className="reader-stage" data-fit="page">
          {error || pdfFailed ? (
            <div className="reader-problem" role="alert" data-testid="reader-book-problem">
              <CircleAlert size={18} />
              <span>{error ?? '这个 PDF 无法打开，可能已损坏或受密码保护。'}</span>
              {error && (
                <Button variant="ghost" size="sm" onClick={retry}>
                  <RotateCcw size={13} />
                  重试
                </Button>
              )}
            </div>
          ) : (
            <span className="settings-note">正在打开…</span>
          )}
        </div>
      </div>
    ),
    document.body,
  );
}

function ReaderSurface({
  copyId,
  book,
  pages,
  savedPageId,
  readState,
  skipped,
  encrypted,
  pdf,
  onClose,
}: {
  copyId: string;
  book: ReaderBook;
  pages: ReaderPage[];
  savedPageId: string | null;
  readState: string;
  skipped: number;
  encrypted: boolean;
  pdf: PDFDocumentProxy | null;
  onClose: () => void;
}) {
  const count = pages.length;
  const startAt = savedPageId ? pages.findIndex((page) => page.id === savedPageId) : 0;
  const [index, setIndex] = useState(Math.max(startAt, 0));
  // The page is gone or changed: it is said, and no other page is passed off as that one.
  const [lostPlace, setLostPlace] = useState(startAt === -1);
  const [choices, setChoicesState] = useState(() => loadChoices(book.id));
  const [fit, setFit] = useState<Fit>('page');
  const [zoom, setZoom] = useState(100);
  const [fullscreen, setFullscreen] = useState(false);
  const [showMarks, setShowMarks] = useState(false);
  const [read, setRead] = useState(readState === 'read');
  const root = useRef<HTMLDivElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const moved = useRef(false);
  const indexNow = useRef(index);
  const scrollToIndex = useRef(true);
  const { bookmarks } = useReaderBookmarks(copyId, book.id);
  const actions = useReaderActions(copyId, book.id);
  const { mode, direction } = choices;
  const spread = useMemo(() => spreadAt(index, count, mode), [index, count, mode]);

  const setChoices = (patch: Partial<Choices>) => {
    const next = { ...choices, ...patch };
    saveChoices(book.id, next);
    scrollToIndex.current = true;
    setChoicesState(next);
  };
  const goTo = useCallback(
    (target: number) => {
      moved.current = true;
      scrollToIndex.current = true;
      setIndex(Math.min(Math.max(target, 0), Math.max(count - 1, 0)));
    },
    [count],
  );
  const step = useCallback(
    (delta: 1 | -1) => {
      if (mode === 'vertical') goTo(index + delta);
      else goTo(turn(index, count, mode, delta));
    },
    [count, goTo, index, mode],
  );

  // Where the user is, saved a moment after they settle; leaving does not lose it. Reaching the end
  // is saved at once, and opening a book saves nothing: only a real move counts.
  const page = pages[index];
  const last = spread[spread.length - 1] === count - 1;
  const { savePosition } = actions;
  const pending = useRef<(() => void) | null>(null);
  useEffect(() => () => pending.current?.(), []);
  useEffect(() => {
    indexNow.current = index;
    if (!page || !moved.current) return undefined;
    const finished = last;
    const send = () => {
      pending.current = null;
      savePosition(page.id, index, count, finished);
    };
    if (finished) {
      setRead(true);
      send();
      return undefined;
    }
    pending.current = send;
    const timer = window.setTimeout(send, 300);
    return () => window.clearTimeout(timer);
  }, [count, index, last, page, savePosition]);

  // Only the pages next to this one are fetched ahead.
  useEffect(() => {
    if (pdf) return;
    for (let offset = -PRELOAD; offset <= PRELOAD + 1; offset += 1) {
      const near = pages[index + offset];
      if (near && offset !== 0) new Image().src = pageUrl(copyId, book.id, near.id);
    }
  }, [book.id, copyId, index, pages, pdf]);

  useEffect(() => {
    const previous = window.document.activeElement as HTMLElement | null;
    root.current?.focus();
    return () => previous?.focus?.();
  }, []);

  useEffect(() => {
    const changed = () => setFullscreen(window.document.fullscreenElement !== null);
    window.document.addEventListener('fullscreenchange', changed);
    return () => {
      window.document.removeEventListener('fullscreenchange', changed);
      if (window.document.fullscreenElement) void window.document.exitFullscreen();
    };
  }, []);

  const toggleFullscreen = () => {
    if (window.document.fullscreenElement) void window.document.exitFullscreen();
    else void root.current?.requestFullscreen().catch(() => undefined);
  };

  // A controlled move scrolls to the page; a turned page starts from its own top.
  useEffect(() => {
    if (!scrollToIndex.current) return;
    scrollToIndex.current = false;
    if (mode === 'vertical') {
      stage.current?.querySelector(`[data-slot="${index}"]`)?.scrollIntoView({ block: 'start' });
    } else {
      stage.current?.scrollTo({ top: 0 });
    }
  }, [index, mode]);

  // In vertical reading, the page across the middle of the screen is the current one.
  useEffect(() => {
    if (mode !== 'vertical' || !stage.current) return undefined;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const slot = Number((entry.target as HTMLElement).dataset.slot);
          if (slot === indexNow.current) continue;
          moved.current = true;
          setIndex(slot);
        }
      },
      { root: stage.current, rootMargin: '-50% 0px -50% 0px' },
    );
    stage.current.querySelectorAll('[data-slot]').forEach((slot) => observer.observe(slot));
    return () => observer.disconnect();
  }, [count, mode]);

  const zoomBy = (delta: number) => {
    setFit('zoom');
    setZoom(Math.min(Math.max(zoom + delta, 25), 400));
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    const target = event.target as HTMLElement;
    if (target.closest('input, select, textarea')) {
      if (event.key === 'Escape') root.current?.focus();
      return;
    }
    const pressingButton = target.tagName === 'BUTTON';
    const keys: Record<string, () => void> = {
      ArrowLeft: () => step(stepForSide('left', direction)),
      ArrowRight: () => step(stepForSide('right', direction)),
      ArrowUp: () => mode === 'vertical' || step(-1),
      ArrowDown: () => mode === 'vertical' || step(1),
      PageUp: () => step(-1),
      PageDown: () => step(1),
      Home: () => goTo(0),
      End: () => goTo(count - 1),
      '+': () => zoomBy(ZOOM_STEP),
      '=': () => zoomBy(ZOOM_STEP),
      '-': () => zoomBy(-ZOOM_STEP),
      f: toggleFullscreen,
      b: () => toggleMark(),
      Escape: () => {
        if (fit !== 'page') setFit('page');
        else onClose();
      },
    };
    if (!pressingButton) keys[' '] = () => step(event.shiftKey ? -1 : 1);
    const action = keys[event.key];
    if (!action) return;
    if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
      if (mode === 'vertical') return;
    }
    event.preventDefault();
    action();
  };

  const onStageClick = (event: MouseEvent<HTMLDivElement>) => {
    if (mode === 'vertical' || fit !== 'page') return;
    const box = event.currentTarget.getBoundingClientRect();
    const place = (event.clientX - box.left) / box.width;
    if (place < 1 / 3) step(stepForSide('left', direction));
    else if (place > 2 / 3) step(stepForSide('right', direction));
  };

  // Down is always onward, whichever way the book reads. A page taller than the view scrolls first
  // and turns at its edge. Vertical reading is simply scrolling, and Ctrl+wheel stays the browser's.
  const wheelBuilt = useRef(0);
  const wheelAt = useRef(-WHEEL_REST_MS);
  const onStageWheel = (event: WheelEvent<HTMLDivElement>) => {
    if (mode === 'vertical' || event.ctrlKey || event.deltaY === 0) return;
    const onward = event.deltaY > 0;
    const { scrollTop, scrollHeight, clientHeight } = event.currentTarget;
    const atEdge = onward ? scrollTop + clientHeight >= scrollHeight - 1 : scrollTop <= 0;
    if (!atEdge) {
      wheelBuilt.current = 0;
      wheelAt.current = event.timeStamp;
      return;
    }
    if (event.timeStamp - wheelAt.current < WHEEL_REST_MS) return;
    const amount = event.deltaMode === 1 ? event.deltaY * WHEEL_LINE : event.deltaY;
    // A change of direction starts counting again.
    wheelBuilt.current = wheelBuilt.current * amount > 0 ? wheelBuilt.current + amount : amount;
    if (Math.abs(wheelBuilt.current) < WHEEL_TURN) return;
    wheelBuilt.current = 0;
    wheelAt.current = event.timeStamp;
    step(onward ? 1 : -1);
  };

  const pageIds = useMemo(() => new Set(pages.map((item) => item.id)), [pages]);
  const markHere = page ? bookmarks.find((mark) => mark.pageId === page.id) : undefined;
  const toggleMark = () => {
    if (!page) return;
    if (markHere) void actions.removeBookmark(markHere.id);
    else void actions.addBookmark(page.id, index);
  };

  const renderPage = (slot: number, lazy: boolean) => {
    const item = pages[slot];
    if (!item) return null;
    if (pdf) {
      const drawn = <PdfPage document={pdf} number={slot + 1} />;
      return lazy ? <NearScreen>{drawn}</NearScreen> : drawn;
    }
    return <ImagePage url={pageUrl(copyId, book.id, item.id)} number={slot + 1} lazy={lazy} />;
  };

  const leftGoes = stepForSide('left', direction);
  const section = page?.section;
  return (
    <div
      className="reader"
      ref={root}
      role="dialog"
      aria-modal="true"
      aria-label={book.name}
      tabIndex={-1}
      data-testid="reader"
      onKeyDown={onKeyDown}
    >
      <div className="reader-bar">
        <span className="reader-title" title={book.name}>
          {book.name}
          {section ? ` · ${section}` : ''}
        </span>
        <span className="reader-turns">
          <Button
            variant="ghost"
            size="icon"
            aria-label={leftGoes === 1 ? '下一页' : '上一页'}
            data-testid="reader-left"
            onClick={() => step(leftGoes)}
          >
            <ChevronLeft size={16} />
          </Button>
          <span className="reader-count" data-testid="reader-count">
            {spread.length > 1 ? `${spread[0]! + 1}-${spread[1]! + 1}` : index + 1} / {count}
          </span>
          <Button
            variant="ghost"
            size="icon"
            aria-label={leftGoes === 1 ? '上一页' : '下一页'}
            data-testid="reader-right"
            onClick={() => step(leftGoes === 1 ? -1 : 1)}
          >
            <ChevronRight size={16} />
          </Button>
        </span>
        <input
          type="range"
          className="reader-seek"
          aria-label="跳到页"
          data-testid="reader-seek"
          min={1}
          max={Math.max(count, 1)}
          value={index + 1}
          onChange={(event) => goTo(Number(event.target.value) - 1)}
        />
        <span className="reader-options">
          <select
            aria-label="阅读方式"
            data-testid="reader-mode"
            value={mode}
            onChange={(event) => setChoices({ mode: event.target.value as ReaderMode })}
          >
            <option value="single">单页</option>
            <option value="double">双页</option>
            <option value="vertical">纵向</option>
          </select>
          <Button
            variant="ghost"
            size="sm"
            data-testid="reader-direction"
            aria-label={`阅读方向：${direction === 'ltr' ? '从左到右' : '从右到左'}`}
            disabled={mode === 'vertical'}
            onClick={() => setChoices({ direction: direction === 'ltr' ? 'rtl' : 'ltr' })}
          >
            <ArrowLeftRight size={14} />
            {direction === 'ltr' ? '左→右' : '右→左'}
          </Button>
          <select
            aria-label="缩放"
            data-testid="reader-fit"
            value={fit === 'zoom' ? 'zoom' : fit}
            onChange={(event) => setFit(event.target.value as Fit)}
          >
            <option value="page">适合页面</option>
            <option value="width">适合宽度</option>
            <option value="zoom">{zoom}%</option>
          </select>
          <Button variant="ghost" size="icon" aria-label="缩小" onClick={() => zoomBy(-ZOOM_STEP)}>
            <ZoomOut size={15} />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label="放大"
            data-testid="reader-zoom-in"
            onClick={() => zoomBy(ZOOM_STEP)}
          >
            <ZoomIn size={15} />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label={markHere ? '删除这页的书签' : '给这页加书签'}
            aria-pressed={Boolean(markHere)}
            data-testid="reader-bookmark"
            onClick={toggleMark}
          >
            {markHere ? <BookmarkCheck size={15} /> : <Bookmark size={15} />}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            aria-expanded={showMarks}
            data-testid="reader-marks-toggle"
            onClick={() => setShowMarks(!showMarks)}
          >
            书签 {bookmarks.length}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            data-testid="reader-read"
            onClick={() => {
              void actions.setRead(!read);
              setRead(!read);
            }}
          >
            {read ? '标为未读' : '标为已读'}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label={fullscreen ? '退出全屏' : '全屏'}
            onClick={toggleFullscreen}
          >
            {fullscreen ? <Minimize size={15} /> : <Maximize size={15} />}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label="关闭阅读器"
            data-testid="reader-close"
            onClick={onClose}
          >
            <X size={16} />
          </Button>
        </span>
      </div>
      {(lostPlace || skipped > 0 || encrypted) && (
        <div className="reader-notice" role="status" data-testid="reader-notice">
          {lostPlace && <span>上次读到的那一页已经改变或不在了，现在从第一页开始。</span>}
          {skipped > 0 && (
            <span>
              {encrypted ? '有加密的页面，' : ''}
              {skipped} 个文件没有打开（加密、过大或路径不安全）。
            </span>
          )}
          {lostPlace && (
            <Button variant="ghost" size="sm" onClick={() => setLostPlace(false)}>
              知道了
            </Button>
          )}
        </div>
      )}
      <div className="reader-body">
        <div
          className="reader-stage"
          ref={stage}
          data-testid="reader-stage"
          data-fit={fit}
          data-mode={mode}
          style={{ '--reader-zoom': `${zoom}%` } as React.CSSProperties}
          onClick={onStageClick}
          onWheel={onStageWheel}
        >
          {count === 0 ? (
            <div className="reader-problem" role="status" data-testid="reader-empty">
              <CircleAlert size={18} />
              <span>这里面没有可以显示的页面。</span>
            </div>
          ) : mode === 'vertical' ? (
            pages.map((item, slot) => (
              <div className="reader-slot" key={item.id} data-slot={slot}>
                {renderPage(slot, true)}
              </div>
            ))
          ) : (
            <div className="reader-spread" data-count={spread.length}>
              {onScreen(spread, direction).map((slot) => (
                <div className="reader-slot" key={pages[slot]?.id ?? slot}>
                  {renderPage(slot, false)}
                </div>
              ))}
            </div>
          )}
        </div>
        {showMarks && (
          <aside className="reader-marks" data-testid="reader-marks">
            <h3>书签</h3>
            {bookmarks.length === 0 && <p className="settings-note">还没有书签。</p>}
            <ul>
              {bookmarks.map((mark) => {
                const here = pages.findIndex((item) => item.id === mark.pageId);
                return (
                  <li key={mark.id}>
                    <button
                      type="button"
                      disabled={!pageIds.has(mark.pageId)}
                      onClick={() => goTo(here)}
                    >
                      第 {(here === -1 ? mark.pageIndex : here) + 1} 页
                      {here === -1 ? '（这页已改变或不在）' : ''}
                    </button>
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label="删除书签"
                      onClick={() => void actions.removeBookmark(mark.id)}
                    >
                      <Trash2 size={13} />
                    </Button>
                  </li>
                );
              })}
            </ul>
          </aside>
        )}
      </div>
    </div>
  );
}
