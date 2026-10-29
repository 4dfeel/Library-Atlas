import { useVirtualizer, defaultRangeExtractor } from '@tanstack/react-virtual';
import { useLayoutEffect, useRef, useState } from 'react';
import { Download, Star } from 'lucide-react';
import type { Game } from '@/lib/data';
import { formatPlaytime, statusLabels } from '@/lib/utils';
import { GameCard, GameCover } from '@/components/game-card';
import { getGridLayout, useMeasuredWidth } from '@/lib/layout';

export type ViewMode = 'grid' | 'list';

export function GameCollection({
  games,
  view,
  onFavorite,
  filterKey,
}: {
  games: Game[];
  view: ViewMode;
  onFavorite: (id: string) => void;
  filterKey: string;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const width = useMeasuredWidth(scrollRef);
  const gridLayout = getGridLayout(width);
  const columns = view === 'list' ? 1 : gridLayout.columns;
  const cardWidth = gridLayout.cardWidth;
  const rowHeight = view === 'list' ? 92 : gridLayout.rowHeight;
  const [focusedIndex, setFocusedIndex] = useState<number | null>(null);
  const focusedControl = useRef<{ gameId: string; control: string } | null>(null);
  const rowCount = Math.ceil(games.length / columns);
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
  useLayoutEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 });
  }, [filterKey]);

  return (
    <div
      className={`library-scroll view-${view}`}
      ref={scrollRef}
      data-testid="library-scroll"
      data-library-scroll
      data-columns={columns}
      tabIndex={-1}
    >
      {view === 'list' && (
        <div className="list-heading" aria-hidden="true">
          <span>游戏名称</span>
          <span>类型</span>
          <span>游玩状态</span>
          <span>累计游玩</span>
          <span>收藏</span>
        </div>
      )}
      <div
        className="virtual-canvas"
        data-testid="game-grid"
        data-columns={columns}
        style={{ height: virtualizer.getTotalSize() }}
        role="list"
        aria-label={view === 'grid' ? '游戏网格' : '游戏列表'}
      >
        {virtualizer.getVirtualItems().map((row) => (
          <div
            className={`virtual-row ${view === 'grid' ? 'grid-row' : ''}`}
            key={`${view}-${row.index}`}
            style={{
              transform: `translateY(${row.start}px)`,
              height: rowHeight,
              gridTemplateColumns: `repeat(${columns}, minmax(0, ${cardWidth}px))`,
            }}
          >
            {games.slice(row.index * columns, row.index * columns + columns).map((game, index) => (
              <div
                key={game.id}
                role="listitem"
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
                  <GameCard game={game} onFavorite={onFavorite} />
                ) : (
                  <article
                    className="game-list-row"
                    data-testid="game-card"
                    data-game-card
                    data-game-id={game.id}
                  >
                    <div className="list-game-title">
                      <GameCover game={game} compact />
                      <div>
                        <h3
                          tabIndex={0}
                          data-focus-key="title"
                          title={`${game.title} · 详情页稍后开放`}
                        >
                          {game.title}
                        </h3>
                        <span className="list-install">
                          {game.installed ? (
                            <>
                              <Download size={12} />
                              已安装
                            </>
                          ) : (
                            '未安装'
                          )}
                        </span>
                      </div>
                    </div>
                    <span className="list-genre">{game.genre}</span>
                    <span className={`list-status status-${game.status}`}>
                      <i />
                      {statusLabels[game.status]}
                    </span>
                    <span className="list-playtime">{formatPlaytime(game.playtimeMinutes)}</span>
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
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
