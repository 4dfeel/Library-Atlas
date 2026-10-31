import { useVirtualizer, defaultRangeExtractor } from '@tanstack/react-virtual';
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowUp, Download, Star } from 'lucide-react';
import type { Game, LibrarySort } from '@/lib/data';
import {
  availabilityLabel,
  formatBytes,
  formatCompactDate,
  statusLabels,
  workMeta,
} from '@/lib/utils';
import { useShell } from '@/app/shell-context';
import { GameCard, GameCover } from '@/components/game-card';
import { WorkMenu } from './work-menu';
import { getGridLayout, useMeasuredWidth } from '@/lib/layout';
import { AppLink } from '@/components/app-link';

export type ViewMode = 'grid' | 'list';

/** Column heading that sorts. The first click uses the direction people expect there. */
function SortHeading({
  label,
  field,
  first,
  sort,
  onSort,
  className,
}: {
  label: string;
  field: string;
  first: 'asc' | 'desc';
  sort: LibrarySort;
  onSort: (sort: LibrarySort) => void;
  className?: string;
}) {
  const [current, direction] = sort.split('-');
  const active = current === field;
  const next = active ? (direction === 'asc' ? 'desc' : 'asc') : first;
  const shown = direction === 'asc' ? '从小到大' : '从大到小';
  return (
    <button
      className={`list-sort${active ? ' is-active' : ''}${className ? ` ${className}` : ''}`}
      data-sort-field={field}
      aria-label={`按${label}排序${active ? `，当前${shown}` : ''}`}
      aria-pressed={active}
      onClick={() => onSort(`${field}-${next}` as LibrarySort)}
    >
      {label}
      {active && (direction === 'asc' ? <ArrowUp size={11} /> : <ArrowDown size={11} />)}
    </button>
  );
}

function Stars({ rating }: { rating: number | null | undefined }) {
  if (!rating) return <span className="list-rating is-empty">—</span>;
  return (
    <span className="list-rating" role="img" aria-label={`${rating} 星`}>
      {'★'.repeat(rating)}
      <i>{'★'.repeat(5 - rating)}</i>
    </span>
  );
}

function rowItems(
  start: number,
  columns: number,
  count: number,
  gameAt: (index: number) => Game | undefined,
) {
  const items: { game: Game | undefined; itemIndex: number }[] = [];
  for (let itemIndex = start; itemIndex < Math.min(count, start + columns); itemIndex++)
    items.push({ game: gameAt(itemIndex), itemIndex });
  return items;
}

export interface CollectionRestore {
  /** First visible item index when the user left this Library entry. */
  anchor?: number;
  focusId?: string;
}

export function GameCollection({
  count,
  gameAt,
  onVisibleRange,
  onScrollChange,
  sort,
  onSort,
  view,
  onFavorite,
  filterKey,
  detailHref,
  onOpenGame,
  restore,
}: {
  count: number;
  /** `undefined` while that item's page is still loading. */
  gameAt: (index: number) => Game | undefined;
  /** Reports the item range on screen, so only those pages are read. */
  onVisibleRange?: (start: number, end: number) => void;
  onScrollChange?: (element: HTMLElement) => void;
  sort: LibrarySort;
  onSort: (sort: LibrarySort) => void;
  view: ViewMode;
  onFavorite: (id: string) => void;
  filterKey: string;
  detailHref: (id: string) => string;
  /** Called before navigating to a detail, with the first visible item index. */
  onOpenGame: (id: string, anchor: number) => void;
  restore?: CollectionRestore;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const width = useMeasuredWidth(scrollRef);
  const gridLayout = getGridLayout(width);
  const columns = view === 'list' ? 1 : gridLayout.columns;
  const cardWidth = gridLayout.cardWidth;
  const rowHeight = view === 'list' ? 92 : gridLayout.rowHeight;
  const [focusedIndex, setFocusedIndex] = useState<number | null>(null);
  const focusedControl = useRef<{ gameId: string; control: string } | null>(null);
  const rowCount = Math.ceil(count / columns);
  // This imperative virtualizer is intentionally outside React Compiler memoization.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => rowHeight,
    overscan: 2,
    rangeExtractor: (range) => {
      const indices = defaultRangeExtractor(range);
      const focusedRow = focusedIndex === null ? -1 : Math.floor(focusedIndex / columns);
      return focusedRow >= 0 && focusedRow < rowCount
        ? [...new Set([...indices, focusedRow])].sort((a, b) => a - b)
        : indices;
    },
  });
  const virtualRows = virtualizer.getVirtualItems();
  const firstRow = virtualRows[0]?.index;
  const lastRow = virtualRows.at(-1)?.index;
  useEffect(() => {
    if (firstRow !== undefined && lastRow !== undefined)
      onVisibleRange?.(firstRow * columns, Math.min(count, (lastRow + 1) * columns));
  }, [firstRow, lastRow, columns, count, onVisibleRange]);
  const previousLayout = useRef({ columns, rowHeight, view });
  useLayoutEffect(() => {
    const old = previousLayout.current;
    const scroll = scrollRef.current;
    if (scroll && (old.columns !== columns || old.rowHeight !== rowHeight || old.view !== view)) {
      const anchor = Math.floor(scroll.scrollTop / old.rowHeight) * old.columns;
      virtualizer.measure();
      scroll.scrollTop = Math.floor(anchor / columns) * rowHeight;
      // A changed column count moves a game to a new row parent, remounting its
      // control. Restore that control only when focus was inside this collection;
      // never take it away from a toolbar or another user-selected element.
      const focused = focusedControl.current;
      if (
        focused &&
        (document.activeElement === document.body || scroll.contains(document.activeElement))
      ) {
        const game = scroll.querySelector<HTMLElement>(
          `[data-game-id="${CSS.escape(focused.gameId)}"]`,
        );
        game
          ?.querySelector<HTMLElement>(`[data-focus-key="${CSS.escape(focused.control)}"]`)
          ?.focus({ preventScroll: true });
      }
    }
    previousLayout.current = { columns, rowHeight, view };
  }, [columns, rowHeight, view, virtualizer]);
  const previousFilterKey = useRef(filterKey);
  useLayoutEffect(() => {
    if (previousFilterKey.current === filterKey) return;
    previousFilterKey.current = filterKey;
    scrollRef.current?.scrollTo({ top: 0 });
  }, [filterKey]);
  // Returning from a detail restores the first visible row once the real column
  // count is known, then focuses the game that was opened if it is still listed.
  const pendingRestore = useRef(restore);
  useLayoutEffect(() => {
    const target = pendingRestore.current;
    const scroll = scrollRef.current;
    if (!target || !scroll || width <= 0) return;
    pendingRestore.current = undefined;
    if (target.anchor !== undefined && target.anchor > 0)
      scroll.scrollTop = Math.floor(target.anchor / columns) * rowHeight;
    const focusId = target.focusId;
    if (!focusId) return;
    let attempts = 0;
    const focusOpened = () => {
      const link = scroll.querySelector<HTMLElement>(
        `[data-game-id="${CSS.escape(focusId)}"] [data-focus-key="title"]`,
      );
      if (link) link.focus({ preventScroll: true });
      else if (++attempts < 5) requestAnimationFrame(focusOpened);
    };
    requestAnimationFrame(focusOpened);
  }, [width, columns, rowHeight]);
  const { notify } = useShell();
  const [menu, setMenu] = useState<{ game: Game; x: number; y: number } | null>(null);
  const closeMenu = useCallback(() => setMenu(null), []);
  const openGame = (id: string) => {
    const scroll = scrollRef.current;
    const anchor = scroll ? Math.floor(scroll.scrollTop / rowHeight) * columns : 0;
    onOpenGame(id, anchor);
  };

  return (
    <div
      className={`library-scroll view-${view}`}
      ref={scrollRef}
      data-testid="library-scroll"
      data-library-scroll
      data-columns={columns}
      tabIndex={-1}
      onScroll={(event) => onScrollChange?.(event.currentTarget)}
    >
      {view === 'list' && (
        <div className="list-heading" role="group" aria-label="按栏目排序">
          <SortHeading
            label="购买日期"
            field="added"
            first="desc"
            sort={sort}
            onSort={onSort}
            className="col-added"
          />
          <SortHeading label="作品名称" field="name" first="asc" sort={sort} onSort={onSort} />
          <SortHeading
            label="制作方"
            field="maker"
            first="asc"
            sort={sort}
            onSort={onSort}
            className="col-maker"
          />
          <SortHeading
            label="作品形式"
            field="genre"
            first="asc"
            sort={sort}
            onSort={onSort}
            className="col-genre"
          />
          <span className="col-status">进度</span>
          <SortHeading
            label="我的评价"
            field="rating"
            first="desc"
            sort={sort}
            onSort={onSort}
            className="col-rating"
          />
          <SortHeading
            label="发售日"
            field="release"
            first="desc"
            sort={sort}
            onSort={onSort}
            className="col-release"
          />
          <SortHeading
            label="大小"
            field="size"
            first="desc"
            sort={sort}
            onSort={onSort}
            className="col-size"
          />
          <span>收藏</span>
        </div>
      )}
      <div
        className="virtual-canvas"
        data-testid="game-grid"
        data-columns={columns}
        style={{ height: virtualizer.getTotalSize() }}
        role="list"
        aria-label={view === 'grid' ? '作品网格' : '作品列表'}
      >
        {virtualRows.map((row) => (
          <div
            className={`virtual-row ${view === 'grid' ? 'grid-row' : ''}`}
            key={`${view}-${row.index}`}
            style={{
              transform: `translateY(${row.start}px)`,
              height: rowHeight,
              gridTemplateColumns: `repeat(${columns}, minmax(0, ${cardWidth}px))`,
            }}
          >
            {rowItems(row.index * columns, columns, count, gameAt).map(
              ({ game, itemIndex }, index) =>
                !game ? (
                  <div
                    key={`pending-${itemIndex}`}
                    role="listitem"
                    data-pending-item
                    className={view === 'grid' ? 'skeleton-card' : 'skeleton-row'}
                  >
                    {view === 'grid' && <div className="skeleton-cover" />}
                    <div className="skeleton-line" />
                    <div className="skeleton-line short" />
                  </div>
                ) : (
                  <div
                    key={game.id}
                    role="listitem"
                    data-index={row.index * columns + index}
                    onContextMenu={(event) => {
                      event.preventDefault();
                      setMenu({ game, x: event.clientX, y: event.clientY });
                    }}
                    onFocusCapture={(event) => {
                      const control = (event.target as HTMLElement).closest<HTMLElement>(
                        '[data-focus-key]',
                      );
                      focusedControl.current = control
                        ? { gameId: game.id, control: control.dataset.focusKey ?? 'title' }
                        : null;
                      setFocusedIndex(row.index * columns + index);
                    }}
                    onBlurCapture={(event) => {
                      if (
                        !event.currentTarget.contains(event.relatedTarget) &&
                        event.relatedTarget instanceof HTMLElement &&
                        event.relatedTarget !== document.body
                      ) {
                        focusedControl.current = null;
                        setFocusedIndex(null);
                      }
                    }}
                  >
                    {view === 'grid' ? (
                      <GameCard
                        game={game}
                        onFavorite={onFavorite}
                        href={detailHref(game.id)}
                        onOpen={() => openGame(game.id)}
                      />
                    ) : (
                      <article
                        className="game-list-row"
                        data-testid="game-card"
                        data-game-card
                        data-game-id={game.id}
                      >
                        <span className="list-date list-added">
                          {formatCompactDate(game.addedAt) ?? '—'}
                        </span>
                        <div className="list-game-title">
                          <GameCover game={game} compact />
                          <div>
                            <h3>
                              <AppLink
                                to={detailHref(game.id)}
                                state={{ fromLibrary: true }}
                                onNavigate={() => openGame(game.id)}
                                className="game-link"
                                data-focus-key="title"
                                title={game.title}
                              >
                                {game.title}
                              </AppLink>
                            </h3>
                            <span className="list-subline">
                              <span className="list-install">
                                {game.installed && <Download size={12} />}
                                {availabilityLabel(game)}
                              </span>
                              <span className="list-playtime">{workMeta(game)}</span>
                            </span>
                          </div>
                        </div>
                        <span className="list-maker" title={game.maker}>
                          {game.maker}
                        </span>
                        <span className="list-genre">{game.genre}</span>
                        <span className={`list-status status-${game.status}`}>
                          <i />
                          {statusLabels[game.status]}
                        </span>
                        <Stars rating={game.rating} />
                        <span className="list-date list-release">
                          {formatCompactDate(game.releaseDate) ?? '—'}
                        </span>
                        <span
                          className="list-date list-size"
                          title={game.file?.sizeBytes ? undefined : '平台没有提供大小'}
                        >
                          {game.file?.sizeBytes ? formatBytes(game.file.sizeBytes) : '—'}
                        </span>
                        <button
                          data-focus-key="favorite"
                          className={`list-favorite${game.favorite ? ' is-favorite' : ''}`}
                          aria-label={`${game.favorite ? '取消收藏' : '收藏'} ${game.title}`}
                          aria-pressed={game.favorite}
                          onClick={() => onFavorite(game.id)}
                        >
                          <Star size={17} fill={game.favorite ? 'currentColor' : 'none'} />
                        </button>
                      </article>
                    )}
                  </div>
                ),
            )}
          </div>
        ))}
      </div>
      {menu && (
        <WorkMenu
          key={`${menu.game.id}-${menu.x}-${menu.y}`}
          game={menu.game}
          x={menu.x}
          y={menu.y}
          detailHref={detailHref(menu.game.id)}
          onOpen={() => openGame(menu.game.id)}
          onFavorite={() => onFavorite(menu.game.id)}
          onClose={closeMenu}
          notify={notify}
        />
      )}
    </div>
  );
}
