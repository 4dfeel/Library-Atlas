import * as TooltipPrimitive from '@radix-ui/react-tooltip';
import { AnimatePresence, MotionConfig, motion, useReducedMotion } from 'motion/react';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowDownWideNarrow,
  ArrowUpRight,
  BookOpen,
  Check,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Download,
  FolderHeart,
  Gamepad2,
  Home,
  Layers3,
  LibraryBig,
  List,
  LockKeyhole,
  Menu,
  Monitor,
  Search,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Star,
  X,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Dialog } from '@/components/ui/dialog';
import { Tooltip } from '@/components/ui/tooltip';
import {
  defaultLibraryFilters,
  useLibrary,
  useToggleFavorite,
  type LibraryFilters,
} from '@/lib/data';
import { GameCollection, type ViewMode } from '@/features/library/game-collection';
import { getGridLayout, useMeasuredWidth } from '@/lib/layout';

type Scenario = 'normal' | 'empty' | 'error' | 'loading';
const demoEnabled = import.meta.env.VITE_DEMO_MODE !== 'false';
const initialParams = new URLSearchParams(window.location.search);
const initialScenario = initialParams.get('state');
const scenario: Scenario =
  initialScenario === 'empty' || initialScenario === 'error' || initialScenario === 'loading'
    ? initialScenario
    : 'normal';

function useNarrow() {
  const [narrow, setNarrow] = useState(() => window.matchMedia('(max-width: 1280px)').matches);
  useEffect(() => {
    const query = window.matchMedia('(max-width: 1280px)');
    const update = () => setNarrow(query.matches);
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  return narrow;
}

function Brand({ collapsed }: { collapsed: boolean }) {
  return (
    <div className="brand">
      <div className="brand-mark" aria-hidden="true">
        <Layers3 size={24} strokeWidth={1.5} />
      </div>
      {!collapsed && (
        <div>
          <span>LIBRARY ATLAS</span>
          <small>你的私人游戏地图</small>
        </div>
      )}
    </div>
  );
}

export function App() {
  const narrow = useNarrow();
  const [manualCollapsed, setManualCollapsed] = useState(false);
  const collapsed = narrow || manualCollapsed;
  const [size, setSize] = useState<1500 | 5000>(initialParams.get('size') === '5000' ? 5000 : 1500);
  const [search, setSearch] = useState(initialParams.get('q') ?? '');
  const [filters, setFilters] = useState<LibraryFilters>({ ...defaultLibraryFilters, search });
  const [view, setView] = useState<ViewMode>(
    initialParams.get('view') === 'list' ? 'list' : 'grid',
  );
  const [aboutOpen, setAboutOpen] = useState(false);
  const [toast, setToast] = useState('');
  const [retryScenario, setRetryScenario] = useState<Scenario>(scenario);
  const searchRef = useRef<HTMLInputElement>(null);
  const reduceMotion = useReducedMotion();
  const query = useLibrary(filters, { size, scenario: demoEnabled ? retryScenario : 'empty' });
  const favorite = useToggleFavorite(size);
  const data = query.data;

  useEffect(() => {
    const timeout = window.setTimeout(() => setFilters((current) => ({ ...current, search })), 140);
    return () => window.clearTimeout(timeout);
  }, [search]);
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
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(''), 2400);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const update = <K extends keyof LibraryFilters>(key: K, value: LibraryFilters[K]) =>
    setFilters((current) => ({ ...current, [key]: value }));
  const reset = () => {
    setSearch('');
    setFilters({ ...defaultLibraryFilters });
  };
  const toggleFavorite = useCallback(
    (id: string) => {
      favorite.mutate(id, {
        onSuccess: () => setToast('收藏已更新 · 仅本次演示会话'),
        onError: () => setToast('未能更新收藏，请重试'),
      });
    },
    [favorite],
  );
  const setDemoSize = (value: 1500 | 5000) => {
    setSize(value);
    const url = new URL(window.location.href);
    url.searchParams.set('size', String(value));
    window.history.replaceState(null, '', url);
  };
  const hasFilters =
    search ||
    filters.genre !== 'all' ||
    filters.status !== 'all' ||
    filters.installed !== 'all' ||
    filters.favoritesOnly;

  return (
    <MotionConfig reducedMotion="user">
      <TooltipPrimitive.Provider>
        <div className={`app-shell${collapsed ? ' sidebar-collapsed' : ''}`}>
          <aside className="sidebar" aria-label="主导航">
            <Brand collapsed={collapsed} />
            <div className="sidebar-nav">
              {!collapsed && <div className="nav-label">我的空间</div>}
              <button
                className="nav-item"
                disabled
                title="首页将在后续检查点开放"
                aria-label="首页 · 稍后开放"
              >
                <Home size={19} />
                {!collapsed && (
                  <>
                    <span>首页</span>
                    <span className="nav-soon">稍后</span>
                  </>
                )}
              </button>
              <a
                aria-label="游戏库"
                href="/library"
                className="nav-item active"
                aria-current="page"
              >
                <LibraryBig size={19} />
                {!collapsed && (
                  <>
                    <span>游戏库</span>
                    <ChevronRight className="nav-chevron" size={16} />
                  </>
                )}
              </a>
              <button
                className="nav-item"
                disabled
                title="收藏夹将在后续阶段开放"
                aria-label="收藏夹 · 稍后开放"
              >
                <FolderHeart size={19} />
                {!collapsed && (
                  <>
                    <span>收藏夹</span>
                    <span className="nav-soon">稍后</span>
                  </>
                )}
              </button>
              <button
                className="nav-item"
                disabled
                title="游玩计划将在后续阶段开放"
                aria-label="游玩计划 · 稍后开放"
              >
                <Gamepad2 size={19} />
                {!collapsed && (
                  <>
                    <span>游玩计划</span>
                    <span className="nav-soon">稍后</span>
                  </>
                )}
              </button>
              {!collapsed && <div className="nav-label second-label">探索与整理</div>}
              <button
                className="nav-item"
                disabled
                title="个性化推荐将在后续阶段开放"
                aria-label="发现 · 稍后开放"
              >
                <Sparkles size={19} />
                {!collapsed && (
                  <>
                    <span>发现</span>
                    <span className="nav-soon">稍后</span>
                  </>
                )}
              </button>
              <button
                className="nav-item"
                disabled
                title="私人空间将在后续阶段开放"
                aria-label="私人空间 · 稍后开放"
              >
                <LockKeyhole size={19} />
                {!collapsed && (
                  <>
                    <span>私人空间</span>
                    <span className="nav-soon">稍后</span>
                  </>
                )}
              </button>
            </div>
            <div className="sidebar-bottom">
              {!collapsed && (
                <div className="local-note">
                  <ShieldCheck size={17} />
                  <span>
                    收藏属于你自己<small>本地优先，安心探索。</small>
                  </span>
                </div>
              )}
              <button className="nav-item" onClick={() => setAboutOpen(true)} title="演示设置">
                <Settings2 size={19} />
                {!collapsed && <span>演示设置</span>}
              </button>
              <div className="sidebar-profile">
                <span className="profile-avatar">A</span>
                {!collapsed && (
                  <span>
                    Atlas 演示空间<small>独立合成数据</small>
                  </span>
                )}
                <span className="online-dot" />
              </div>
            </div>
          </aside>

          <div className="workspace">
            <header className="topbar">
              <div className="topbar-left">
                <Tooltip
                  content={
                    narrow ? '窗口较窄，侧栏已自动收起' : collapsed ? '展开侧栏' : '收起侧栏'
                  }
                >
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={collapsed ? '展开侧栏' : '收起侧栏'}
                    disabled={narrow}
                    onClick={() => setManualCollapsed((value) => !value)}
                  >
                    <Menu size={19} />
                  </Button>
                </Tooltip>
                <span className="breadcrumb-root">我的空间</span>
                <ChevronRight size={13} />
                <span>游戏库</span>
              </div>
              <div className="topbar-right">
                <span className="demo-indicator">
                  <span />
                  {demoEnabled ? 'DEMO · 演示模式' : '真实数据尚未接入'}
                </span>
                <span className="topbar-divider" />
                <Tooltip content="关于本次演示">
                  <Button
                    size="icon"
                    variant="ghost"
                    aria-label="关于演示"
                    onClick={() => setAboutOpen(true)}
                  >
                    <CircleHelp size={18} />
                  </Button>
                </Tooltip>
              </div>
            </header>

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
                    <h1 id="library-title">我的游戏库</h1>
                    <span className="title-count">
                      {(data?.totalVisible ?? 0).toLocaleString('zh-CN')}
                    </span>
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

              <section className="library-controls" aria-label="游戏库工具栏">
                <div className="collection-tabs" aria-label="快捷筛选">
                  <button
                    aria-pressed={!filters.favoritesOnly && filters.installed === 'all'}
                    className={
                      !filters.favoritesOnly && filters.installed === 'all' ? 'selected' : ''
                    }
                    onClick={() => {
                      update('favoritesOnly', false);
                      update('installed', 'all');
                    }}
                  >
                    <BookOpen size={16} />
                    全部游戏<span>{(data?.totalVisible ?? 0).toLocaleString('zh-CN')}</span>
                  </button>
                  <button
                    aria-pressed={filters.installed === 'installed'}
                    className={filters.installed === 'installed' ? 'selected' : ''}
                    onClick={() => {
                      update('favoritesOnly', false);
                      update('installed', 'installed');
                    }}
                  >
                    <Download size={16} />
                    已安装<span>{(data?.installedCount ?? 0).toLocaleString('zh-CN')}</span>
                  </button>
                  <button
                    aria-pressed={filters.favoritesOnly}
                    className={filters.favoritesOnly ? 'selected' : ''}
                    onClick={() => {
                      update('favoritesOnly', true);
                      update('installed', 'all');
                    }}
                  >
                    <Star size={16} />
                    我的收藏<span>{(data?.favoriteCount ?? 0).toLocaleString('zh-CN')}</span>
                  </button>
                  <span className="tabs-spacer" />
                  <span className="demo-data-note">合成数据 · 非真实游玩记录</span>
                </div>
                <div className="filter-toolbar">
                  <div className="search-field">
                    <Search size={17} />
                    <Input
                      ref={searchRef}
                      aria-label="搜索游戏"
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
                    </select>
                    <ChevronDown size={13} />
                  </div>
                  <div className="filter-select">
                    <select
                      aria-label="游玩状态"
                      value={filters.status}
                      onChange={(event) =>
                        update('status', event.target.value as LibraryFilters['status'])
                      }
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
                      aria-label="安装状态"
                      value={filters.installed}
                      onChange={(event) =>
                        update('installed', event.target.value as LibraryFilters['installed'])
                      }
                    >
                      <option value="all">全部安装状态</option>
                      <option value="installed">已安装</option>
                      <option value="not-installed">未安装</option>
                    </select>
                    <ChevronDown size={13} />
                  </div>
                  <span className="toolbar-spacer" />
                  <div className="filter-select sort-select">
                    <ArrowDownWideNarrow size={16} />
                    <select
                      aria-label="排序"
                      value={filters.sort}
                      onChange={(event) =>
                        update('sort', event.target.value as LibraryFilters['sort'])
                      }
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
                    <span>{(data?.filteredCount ?? 0).toLocaleString('zh-CN')}</span> 款游戏
                    {hasFilters && (
                      <button onClick={reset}>
                        清除筛选
                        <X size={12} />
                      </button>
                    )}
                    {query.isFetching && !query.isPending && (
                      <span className="updating-label">正在更新…</span>
                    )}
                  </p>
                  <span>
                    详情页稍后开放 <ArrowUpRight size={12} />
                  </span>
                </div>
              </section>

              {!demoEnabled ? (
                <FeedbackState
                  kind="empty"
                  title="真实资料尚未接入"
                  description="此检查点仅提供独立演示空间。开启 VITE_DEMO_MODE 后可浏览合成收藏。"
                />
              ) : query.isPending ? (
                <LoadingState
                  onRetry={() => {
                    setRetryScenario('normal');
                    void query.refetch();
                  }}
                />
              ) : query.isError ? (
                <FeedbackState
                  kind="error"
                  title="暂时未能读取游戏库"
                  description="你的演示收藏仍然安全。请重试，继续探索。"
                  action="重新加载"
                  onAction={() => {
                    setRetryScenario('normal');
                    void query.refetch();
                  }}
                />
              ) : data?.items.length ? (
                <GameCollection
                  games={data.items}
                  view={view}
                  onFavorite={toggleFavorite}
                  filterKey={JSON.stringify(filters) + size}
                />
              ) : (
                <FeedbackState
                  kind="empty"
                  title={hasFilters ? '还没有找到这段冒险' : '收藏的故事，从这里开始'}
                  description={
                    hasFilters
                      ? '试试其他关键词，或放宽筛选条件。'
                      : '这里还没有游戏。切换回完整演示，看看未来收藏的模样。'
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
                  本地演示 · 不连接 Steam
                </span>
                <button onClick={() => setAboutOpen(true)}>
                  {size.toLocaleString('zh-CN')} 款测试场景
                  <ChevronDown size={12} />
                </button>
                <span>
                  LIBRARY ATLAS<span className="footer-version">PREVIEW 01</span>
                </span>
              </footer>
            </main>
          </div>
        </div>
        <Dialog
          open={aboutOpen}
          onOpenChange={setAboutOpen}
          title="你的演示空间"
          description="当前展示的游戏、封面与游玩记录均为合成资料，与真实 Steam 库存完全隔离。"
        >
          <div className="demo-settings">
            <div>
              <span className="eyebrow">DATA SCENARIO</span>
              <h3>选择收藏规模</h3>
              <p>固定种子生成；收藏标记仅在本次会话保留。</p>
            </div>
            <div className="scenario-buttons">
              {([1500, 5000] as const).map((value) => (
                <button
                  key={value}
                  className={size === value ? 'selected' : ''}
                  aria-pressed={size === value}
                  onClick={() => setDemoSize(value)}
                >
                  <span>
                    {value.toLocaleString('zh-CN')}
                    <small>款游戏</small>
                  </span>
                  {size === value && <Check size={18} />}
                </button>
              ))}
            </div>
            <div className="demo-explanation">
              <ShieldCheck size={18} />
              <p>
                私人、隐藏与待确认条目已在数据选择层排除。当前未接入真实
                API，详情、首页和私人空间等待后续检查点开放。
              </p>
            </div>
            <Button variant="secondary" onClick={() => setAboutOpen(false)}>
              继续浏览
              <ChevronRight size={15} />
            </Button>
          </div>
        </Dialog>
        <AnimatePresence>
          {toast && (
            <motion.div
              className="toast"
              role="status"
              initial={{ opacity: 0, y: reduceMotion ? 0 : 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
            >
              <Check size={16} />
              {toast}
            </motion.div>
          )}
        </AnimatePresence>
      </TooltipPrimitive.Provider>
    </MotionConfig>
  );
}

function FeedbackState({
  kind,
  title,
  description,
  action,
  onAction,
}: {
  kind: 'error' | 'empty';
  title: string;
  description: string;
  action?: string;
  onAction?: () => void;
}) {
  return (
    <div className={`feedback-state feedback-${kind}`} role={kind === 'error' ? 'alert' : 'status'}>
      <div className="feedback-illustration">
        <span />
        <LibraryBig size={38} strokeWidth={1} />
      </div>
      <span className="eyebrow">{kind === 'error' ? 'A SMALL DETOUR' : 'UNCHARTED TERRITORY'}</span>
      <h2>{title}</h2>
      <p>{description}</p>
      {action && (
        <Button variant="secondary" onClick={onAction}>
          {action}
          <ChevronRight size={16} />
        </Button>
      )}
    </div>
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
      aria-label="正在读取本地游戏库"
      role="status"
    >
      <p className="sr-only">正在读取本地游戏库</p>
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
