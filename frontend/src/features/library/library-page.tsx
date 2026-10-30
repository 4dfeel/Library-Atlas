import { motion, useReducedMotion } from 'motion/react';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowDownWideNarrow,
  ChevronDown,
  Clapperboard,
  Gamepad2,
  Headphones,
  Image,
  Layers3,
  LayoutGrid,
  List,
  Monitor,
  Package,
  Shapes,
  Search,
  SlidersHorizontal,
  Star,
  X,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { FeedbackState } from '@/components/feedback-state';
import {
  defaultLibraryFilters,
  useLibraryCollection,
  useToggleFavorite,
  useWorkspace,
  type DemoScenario,
  type DemoSize,
  type LibraryFilters,
  workKinds,
} from '@/lib/data';
import { kindLabels } from '@/lib/utils';
import { getGridLayout, useMeasuredWidth } from '@/lib/layout';
import { gameHref, matchRoute, patchHistoryState, readHistoryState } from '@/lib/router';
import { ReadFailure, RealLibraryEmpty } from '@/features/workspace/service-state';
import { GameCollection, type CollectionRestore, type ViewMode } from './game-collection';
import { libraryUrl, parseLibraryUrl } from './library-url';

const kindIcons: Record<LibraryFilters['kind'], typeof LayoutGrid> = {
  all: LayoutGrid,
  game: Gamepad2,
  'non-game': Shapes,
  image: Image,
  video: Clapperboard,
  audio: Headphones,
  other: Package,
};

const tabKinds: LibraryFilters['kind'][] = ['all', 'game', 'non-game', ...workKinds.slice(1)];

function scenarioFromUrl(): DemoScenario {
  const value = new URLSearchParams(window.location.search).get('state');
  return value === 'empty' || value === 'error' || value === 'loading' ? value : 'normal';
}

export function LibraryPage({
  size,
  onAbout,
  notify,
}: {
  size: DemoSize;
  onAbout: () => void;
  notify: (message: string, tone?: 'success' | 'error') => void;
}) {
  // Search, filters, sort and view are read from this history entry's URL, so
  // returning from a detail (or refreshing) restores them without extra storage.
  const [initial] = useState(() => parseLibraryUrl(window.location.search));
  const [restore] = useState<CollectionRestore & { focusSearch?: boolean }>(() => {
    const state = readHistoryState();
    return {
      anchor: state.libraryAnchor,
      focusId: state.libraryFocusId,
      focusSearch: state.focusSearch,
    };
  });
  const [search, setSearch] = useState(initial.filters.search);
  const [filters, setFilters] = useState<LibraryFilters>(initial.filters);
  const [view, setView] = useState<ViewMode>(initial.view);
  const [retryScenario, setRetryScenario] = useState<DemoScenario>(scenarioFromUrl);
  const searchRef = useRef<HTMLInputElement>(null);
  const reduceMotion = useReducedMotion();
  const { isDemo, isTestLibrary } = useWorkspace();
  const collection = useLibraryCollection(filters, { size, scenario: retryScenario });
  const favorite = useToggleFavorite(size);
  const data = collection.summary;

  useEffect(() => {
    const timeout = window.setTimeout(
      () => setFilters((current) => (current.search === search ? current : { ...current, search })),
      140,
    );
    return () => window.clearTimeout(timeout);
  }, [search]);
  useEffect(() => {
    // History can already have moved on (Forward to a detail) before this page unmounts;
    // never write Library state onto another page's URL.
    if (matchRoute(window.location.pathname).name !== 'library') return;
    const next = libraryUrl(window.location.href, { filters, view });
    if (next !== window.location.pathname + window.location.search)
      window.history.replaceState(window.history.state, '', next);
  }, [filters, view]);
  useEffect(() => {
    const handleSearch = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        searchRef.current?.focus();
        searchRef.current?.select();
      }
    };
    window.addEventListener('keydown', handleSearch);
    return () => window.removeEventListener('keydown', handleSearch);
  }, []);
  useEffect(() => {
    document.title = '作品库 · Library Atlas';
    if (restore.focusSearch) {
      searchRef.current?.focus();
      patchHistoryState({ focusSearch: undefined });
    }
  }, [restore.focusSearch]);

  const update = <K extends keyof LibraryFilters>(key: K, value: LibraryFilters[K]) =>
    setFilters((current) => ({ ...current, [key]: value }));
  const reset = () => {
    setSearch('');
    setFilters({ ...defaultLibraryFilters });
  };
  const toggleFavorite = useCallback(
    (id: string) => {
      favorite.mutate(id, {
        onSuccess: () => notify(isDemo ? '收藏已更新 · 演示修改保存在本机' : '收藏已更新'),
        onError: () => notify('未能更新收藏，请重试', 'error'),
      });
    },
    [favorite, isDemo, notify],
  );
  const detailHref = useCallback((id: string) => gameHref(id, size), [size]);
  const openGame = useCallback((id: string, anchor: number) => {
    // Saved on this Library entry, so Back (browser or in-app) lands where it left.
    patchHistoryState({ libraryAnchor: anchor, libraryFocusId: id, focusSearch: undefined });
  }, []);
  const hasFilters =
    search ||
    filters.genre !== 'all' ||
    filters.status !== 'all' ||
    filters.installed !== 'all' ||
    filters.kind !== 'all' ||
    filters.platform !== 'all' ||
    filters.favoritesOnly;

  return (
    <main className="library-page">
      <motion.section
        className="library-intro"
        initial={reduceMotion ? false : { opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2 }}
        aria-labelledby="library-title"
      >
        <div className="intro-copy">
          <span className="eyebrow">THE COLLECTION</span>
          <div className="title-line">
            <h1 id="library-title">我的作品库</h1>
            <span className="title-count">{(data?.totalVisible ?? 0).toLocaleString('zh-CN')}</span>
          </div>
          <p>每一段冒险，都有它的位置。</p>
          <div className="intro-footnote">
            <span className="intro-line" />
            <span>发现熟悉收藏中的，下一份心动。</span>
          </div>
        </div>
        <div className="intro-art" aria-hidden="true">
          <img src="/demo/covers/cover-01.svg" alt="" />
          <div className="intro-art-shade" />
          <div className="intro-art-caption">
            <span>CURATED WORLDS</span>
            <p>有些世界，值得再次出发。</p>
            <span className="art-line" />
          </div>
          <span className="art-serial">ATLAS / 001</span>
        </div>
      </motion.section>

      <section className="library-controls" aria-label="作品库工具栏">
        <div className="collection-tabs" role="group" aria-label="作品类型">
          {tabKinds.map((kind) => {
            const Icon = kindIcons[kind];
            const count =
              kind === 'all'
                ? data?.totalVisible
                : kind === 'non-game'
                  ? data && data.totalVisible - data.kindCounts.game
                  : data?.kindCounts[kind];
            return (
              <button
                key={kind}
                aria-pressed={filters.kind === kind}
                className={filters.kind === kind ? 'selected' : ''}
                onClick={() => setFilters((current) => ({ ...current, kind, genre: 'all' }))}
              >
                <Icon size={16} />
                {kind === 'all' ? '全部' : kind === 'non-game' ? '非游戏' : kindLabels[kind]}
                <span>{(count ?? 0).toLocaleString('zh-CN')}</span>
              </button>
            );
          })}
          <span className="tabs-spacer" />
          {(isDemo || isTestLibrary) && (
            <span className="demo-data-note">
              {isDemo ? '合成数据 · 非真实游玩记录' : '测试数据 · 合成样本，不是同步结果'}
            </span>
          )}
        </div>
        <div className="filter-toolbar">
          <div className="search-field">
            <Search size={17} />
            <Input
              ref={searchRef}
              aria-label="搜索作品"
              placeholder="搜索你的下一段冒险…"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            {search ? (
              <button aria-label="清除搜索" onClick={() => setSearch('')}>
                <X size={15} />
              </button>
            ) : (
              <kbd>Ctrl K</kbd>
            )}
          </div>
          <div className="filter-select">
            <label htmlFor="genre">
              <SlidersHorizontal size={15} />
            </label>
            <select
              id="genre"
              aria-label="类型"
              value={filters.genre}
              onChange={(event) => update('genre', event.target.value)}
            >
              <option value="all">所有类型</option>
              {data?.genres.map((genre) => (
                <option key={genre} value={genre}>
                  {genre}
                </option>
              ))}
              {/* Keep a restored URL value selectable while results are loading. */}
              {filters.genre !== 'all' && !data?.genres.includes(filters.genre) && (
                <option value={filters.genre}>{filters.genre}</option>
              )}
            </select>
            <ChevronDown size={13} />
          </div>
          <div className="filter-select">
            <select
              aria-label="游玩状态"
              value={filters.status}
              onChange={(event) => update('status', event.target.value as LibraryFilters['status'])}
            >
              <option value="all">所有状态</option>
              <option value="unplayed">未开始</option>
              <option value="playing">在玩</option>
              <option value="completed">已完成</option>
              <option value="paused">搁置</option>
            </select>
            <ChevronDown size={13} />
          </div>
          <div className="filter-select install-filter">
            <select
              aria-label="本机状态"
              value={filters.installed}
              onChange={(event) =>
                update('installed', event.target.value as LibraryFilters['installed'])
              }
            >
              <option value="all">全部本机状态</option>
              <option value="installed">已安装 / 已下载</option>
              <option value="not-installed">未在本机</option>
            </select>
            <ChevronDown size={13} />
          </div>
          <div className="filter-select">
            <select
              aria-label="平台"
              value={filters.platform}
              onChange={(event) =>
                update('platform', event.target.value as LibraryFilters['platform'])
              }
            >
              <option value="all">全部平台</option>
              <option value="steam">Steam</option>
              <option value="dlsite">DLsite</option>
            </select>
            <ChevronDown size={13} />
          </div>
          <button
            className={`favorite-filter${filters.favoritesOnly ? ' selected' : ''}`}
            aria-pressed={filters.favoritesOnly}
            onClick={() => update('favoritesOnly', !filters.favoritesOnly)}
          >
            <Star size={15} fill={filters.favoritesOnly ? 'currentColor' : 'none'} />
            仅收藏<span>{(data?.favoriteCount ?? 0).toLocaleString('zh-CN')}</span>
          </button>
          <span className="toolbar-spacer" />
          <div className="filter-select sort-select">
            <ArrowDownWideNarrow size={16} />
            <select
              aria-label="排序"
              value={filters.sort}
              onChange={(event) => update('sort', event.target.value as LibraryFilters['sort'])}
            >
              <option value="curated">收藏顺序</option>
              <option value="name-asc">名称 A → Z</option>
              <option value="name-desc">名称 Z → A</option>
              <option value="playtime-desc">游玩时长 ↓</option>
              <option value="playtime-asc">游玩时长 ↑</option>
            </select>
            <ChevronDown size={13} />
          </div>
          <div className="view-toggle" aria-label="视图切换">
            <button
              aria-label="网格视图"
              aria-pressed={view === 'grid'}
              className={view === 'grid' ? 'selected' : ''}
              onClick={() => setView('grid')}
            >
              <Layers3 size={17} />
            </button>
            <button
              aria-label="列表视图"
              aria-pressed={view === 'list'}
              className={view === 'list' ? 'selected' : ''}
              onClick={() => setView('list')}
            >
              <List size={18} />
            </button>
          </div>
        </div>
        <div
          className="results-summary"
          data-testid="library-results"
          data-count={data?.filteredCount ?? 0}
        >
          <p aria-live="polite">
            <span>{(data?.filteredCount ?? 0).toLocaleString('zh-CN')}</span> 部作品
            {hasFilters && (
              <button onClick={reset}>
                清除筛选
                <X size={12} />
              </button>
            )}
            {collection.isFetching && !collection.isPending && (
              <span className="updating-label">正在更新…</span>
            )}
            {collection.isStale && (
              <button data-testid="library-stale" onClick={collection.refetch}>
                部分内容未能更新，点此重试
              </button>
            )}
          </p>
          <span>点击作品查看详情</span>
        </div>
      </section>

      {collection.isPending ? (
        <LoadingState
          onRetry={() => {
            setRetryScenario('normal');
            collection.refetch();
          }}
        />
      ) : collection.error && !isDemo ? (
        <ReadFailure error={collection.error} onRetry={collection.refetch} />
      ) : collection.error ? (
        <FeedbackState
          kind="error"
          title="暂时未能读取作品库"
          description="你的演示收藏仍然安全。请重试，继续探索。"
          action="重新加载"
          onAction={() => {
            setRetryScenario('normal');
            collection.refetch();
          }}
        />
      ) : collection.count ? (
        <GameCollection
          count={collection.count}
          gameAt={collection.gameAt}
          onVisibleRange={collection.onVisibleRange}
          view={view}
          onFavorite={toggleFavorite}
          filterKey={JSON.stringify(filters) + size}
          detailHref={detailHref}
          onOpenGame={openGame}
          restore={restore}
        />
      ) : !isDemo && !hasFilters ? (
        <RealLibraryEmpty />
      ) : (
        <FeedbackState
          kind="empty"
          title={hasFilters ? '还没有找到这段冒险' : '收藏的故事，从这里开始'}
          description={
            hasFilters
              ? '试试其他关键词，或放宽筛选条件。'
              : '这里还没有作品。切换回完整演示，看看未来收藏的模样。'
          }
          action={hasFilters ? '清除筛选' : '浏览演示收藏'}
          onAction={() => {
            reset();
            setRetryScenario('normal');
          }}
        />
      )}

      <footer className="library-footer">
        <span>
          <Monitor size={12} />
          {isDemo
            ? '本地演示 · 不连接 Steam / DLsite'
            : isTestLibrary
              ? '隔离测试库 · 不连接 Steam / DLsite'
              : '本地资料库'}
        </span>
        <button onClick={onAbout}>
          {isDemo ? `${size.toLocaleString('zh-CN')} 款测试场景` : '资料库状态'}
          <ChevronDown size={12} />
        </button>
        <span>
          LIBRARY ATLAS<span className="footer-version">PREVIEW 02</span>
        </span>
      </footer>
    </main>
  );
}

function LoadingState({ onRetry }: { onRetry: () => void }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const width = useMeasuredWidth(containerRef);
  const { columns, cardWidth, rowHeight } = getGridLayout(width);
  const rows = Math.max(3, Math.ceil(window.innerHeight / rowHeight));
  const [delayed, setDelayed] = useState(false);
  useEffect(() => {
    const timeout = window.setTimeout(() => setDelayed(true), 10_000);
    return () => window.clearTimeout(timeout);
  }, []);
  return (
    <div
      className="loading-state"
      ref={containerRef}
      data-columns={columns}
      style={{
        gridTemplateColumns: `repeat(${columns}, minmax(0, ${cardWidth}px))`,
        gridAutoRows: `${rowHeight - 20}px`,
      }}
      aria-label="正在读取本地作品库"
      role="status"
    >
      <p className="sr-only">正在读取本地作品库</p>
      {delayed && (
        <div className="loading-explanation">
          读取时间比预期更长。
          <Button variant="secondary" size="sm" onClick={onRetry}>
            重新读取
          </Button>
        </div>
      )}
      {Array.from({ length: columns * rows }, (_, index) => (
        <div className="skeleton-card" key={index}>
          <div className="skeleton-cover" />
          <div className="skeleton-line" />
          <div className="skeleton-line short" />
        </div>
      ))}
    </div>
  );
}
