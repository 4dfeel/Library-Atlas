import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from 'react';
import {
  ArrowRight,
  Download,
  Flame,
  Hourglass,
  LayoutGrid,
  PlugZap,
  RefreshCw,
  Shapes,
  Sparkles,
  Tags,
  Timer,
} from 'lucide-react';
import { AppLink } from '@/components/app-link';
import { FeedbackState } from '@/components/feedback-state';
import { GameCover } from '@/components/game-card';
import { useShell } from '@/app/shell-context';
import { realConnectionState } from '@/features/workspace/connection-labels';
import { ConnectionBadge } from '@/features/workspace/sources-dialog';
import { ReadFailure, RealLibraryEmpty } from '@/features/workspace/service-state';
import { HeroBackdrop } from '@/features/game-detail/game-hero';
import { libraryHrefFor } from '@/features/library/library-url';
import {
  dashboardScopes,
  scopeLibraryFilters,
  useDashboard,
  useDownloads,
  useExtractions,
  useRealSources,
  useWorkspace,
  type DashboardResult,
  type DashboardScope,
  type Game,
  type GameStatus,
} from '@/lib/data';
import { useMeasuredWidth } from '@/lib/layout';
import { gameHref, patchHistoryState } from '@/lib/router';
import {
  availabilityLabel,
  formatShortDate,
  kindLabels,
  platformLabels,
  statusLabels,
  usageVerbs,
  workMeta,
} from '@/lib/utils';
// Recharts is only needed below the fold; keep it out of the initial bundle.
const charts = () => import('./dashboard-charts');
const PlaytimeChart = lazy(() => charts().then((m) => ({ default: m.PlaytimeChart })));
const GenreChart = lazy(() => charts().then((m) => ({ default: m.GenreChart })));
const KindChart = lazy(() => charts().then((m) => ({ default: m.KindChart })));
const chartFallback = <div className="chart-box chart-loading" aria-hidden="true" />;

const scopeLabels: Record<DashboardScope, string> = {
  all: '全部作品',
  games: '全部游戏',
  steam: 'Steam 游戏',
  'dlsite-games': 'DLsite 游戏',
  'dlsite-media': 'DLsite 其他作品',
};

function readScope(): DashboardScope {
  const value = new URLSearchParams(window.location.search).get('scope');
  return dashboardScopes.includes(value as DashboardScope) ? (value as DashboardScope) : 'all';
}

const hours = (minutes: number) =>
  (minutes / 60).toLocaleString('zh-CN', { maximumFractionDigits: minutes < 6000 ? 1 : 0 });

/** Detail links from the Dashboard come back here with history Back. */
function WorkLink({
  game,
  className,
  children,
  label,
}: {
  game: Game;
  className?: string;
  children: ReactNode;
  label?: string;
}) {
  return (
    <AppLink
      to={gameHref(game.id)}
      state={{ fromDashboard: true }}
      className={className}
      aria-label={label}
    >
      {children}
    </AppLink>
  );
}

function Stat({
  label,
  value,
  unit,
  note,
  href,
  testId,
}: {
  label: string;
  value: string;
  unit?: string;
  note: string;
  href?: string;
  testId?: string;
}) {
  return (
    <div className="dash-stat" data-testid={testId}>
      <dt>{label}</dt>
      <dd>
        <span className="dash-stat-value">
          {href ? <AppLink to={href}>{value}</AppLink> : value}
          {unit && <small>{unit}</small>}
        </span>
        <span className="dash-stat-note">{note}</span>
      </dd>
    </div>
  );
}

function Stats({ data }: { data: DashboardResult }) {
  const t = data.totals;
  const scoped = libraryHrefFor(scopeLibraryFilters(data.scope));
  if (!data.hasGames)
    return (
      <dl className="dash-stats">
        <Stat
          label="作品总数"
          value={t.works.toLocaleString('zh-CN')}
          unit="部"
          note="DLsite 非游戏作品"
          href={scoped}
          testId="stat-works"
        />
        <Stat
          label="有体验记录"
          value={t.usedNonGames.toLocaleString('zh-CN')}
          unit="部"
          note="阅读、观看或收听"
        />
        <Stat
          label="待体验"
          value={data.backlog.unplayed.toLocaleString('zh-CN')}
          unit="部"
          note="按你标记的状态"
        />
        <Stat label="已下载" value={t.local.toLocaleString('zh-CN')} unit="部" note="本机可用" />
      </dl>
    );
  const recorded = t.games - t.unknownPlaytimeGames;
  return (
    <dl className="dash-stats">
      <Stat
        label={data.scope === 'all' ? '作品总数' : '游戏总数'}
        value={(data.scope === 'all' ? t.works : t.games).toLocaleString('zh-CN')}
        unit={data.scope === 'all' ? '部' : '款'}
        note={
          data.scope === 'all'
            ? `其中游戏 ${t.games.toLocaleString('zh-CN')} 款`
            : scopeLabels[data.scope]
        }
        href={scoped}
        testId="stat-works"
      />
      <Stat
        label="已游玩游戏"
        // With no records at all, 0 would read as "played nothing"; say unknown instead.
        value={recorded ? t.playedGames.toLocaleString('zh-CN') : '未提供'}
        unit={recorded ? '款' : undefined}
        note={
          t.unknownPlaytimeGames
            ? `另有 ${t.unknownPlaytimeGames.toLocaleString('zh-CN')} 款无游玩记录，未计入`
            : '有游玩记录且时长大于 0'
        }
        testId="stat-played"
      />
      <Stat
        label="未开始游戏"
        value={t.unstartedGames.toLocaleString('zh-CN')}
        unit="款"
        note="按你标记的“未开始”状态"
        href={libraryHrefFor({
          ...scopeLibraryFilters(data.scope),
          kind: 'game',
          status: 'unplayed',
        })}
        testId="stat-unstarted"
      />
      <Stat
        label="累计游玩"
        value={recorded ? hours(t.playtimeMinutes) : '未提供'}
        unit={recorded ? '小时' : undefined}
        note={
          recorded
            ? `来自 ${recorded.toLocaleString('zh-CN')} 款有记录的游戏`
            : '该来源不提供游玩时长'
        }
        testId="stat-playtime"
      />
    </dl>
  );
}

function ScopeSwitch({
  scope,
  onChange,
}: {
  scope: DashboardScope;
  onChange: (scope: DashboardScope) => void;
}) {
  return (
    <div className="scope-switch" role="group" aria-label="首页范围">
      {dashboardScopes.map((value) => (
        <button
          key={value}
          aria-pressed={scope === value}
          className={scope === value ? 'selected' : ''}
          onClick={() => onChange(value)}
        >
          {scopeLabels[value]}
        </button>
      ))}
    </div>
  );
}

function Featured({
  game,
  onNext,
  canCycle,
}: {
  game: Game;
  onNext: () => void;
  canCycle: boolean;
}) {
  const used = formatShortDate(game.lastPlayedAt);
  return (
    <div className="dash-feature" data-testid="featured" data-game-id={game.id}>
      <WorkLink game={game} className="dash-feature-cover" label={`查看 ${game.title}`}>
        <GameCover game={game} priority />
      </WorkLink>
      <div className="dash-feature-copy">
        <div className="hero-eyebrow">
          <span className="feature-chip">
            <Sparkles size={12} />
            今日精选
          </span>
          <span className="platform-chip">{platformLabels[game.platform]}</span>
          <span>
            {kindLabels[game.kind]} · {game.genre}
          </span>
        </div>
        <h2 className="dash-feature-title" title={game.title}>
          {game.title}
        </h2>
        <p className="dash-feature-meta">
          <span className={`status-label status-${game.status}`}>
            <i className="status-dot" />
            {statusLabels[game.status]}
          </span>
          <span>{availabilityLabel(game)}</span>
          <span>
            {game.platform === 'steam'
              ? workMeta(game)
              : used
                ? `最近${usageVerbs[game.kind]} · ${used}`
                : '暂无体验记录'}
          </span>
        </p>
        <div className="hero-actions">
          <WorkLink game={game} className="button button-primary">
            查看详情
            <ArrowRight size={16} />
          </WorkLink>
          {canCycle && (
            <button className="button button-ghost" onClick={onNext}>
              <RefreshCw size={15} />
              换一个
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function RecentRow({ data }: { data: DashboardResult }) {
  const ref = useRef<HTMLDivElement>(null);
  const width = useMeasuredWidth(ref);
  // Show whole cards only; never render hidden-but-focusable extras.
  const count = width
    ? Math.max(2, Math.min(data.recent.length, Math.floor((width + 16) / 166)))
    : 0;
  const gameOnly = data.scope !== 'all' && data.hasGames;
  return (
    <section className="dash-recent" aria-labelledby="recent-title">
      <div className="dash-section-heading">
        <h2 id="recent-title">
          <Timer size={16} />
          {gameOnly ? '最近游玩' : '最近体验'}
        </h2>
        <span className="dash-section-note">按最近使用排序</span>
      </div>
      <div
        className="recent-row"
        ref={ref}
        data-testid="recent-row"
        style={{ gridTemplateColumns: count ? `repeat(${count}, minmax(0, 1fr))` : undefined }}
      >
        {data.recent.length === 0 ? (
          <p className="section-empty">
            这个范围还没有使用记录。购买或加入日期不会被当作最近体验。
          </p>
        ) : (
          data.recent.slice(0, count).map((game) => (
            <WorkLink key={game.id} game={game} className="recent-card">
              <GameCover game={game} />
              <span className="recent-title">{game.title}</span>
              <span className="recent-meta">
                最近{usageVerbs[game.kind]} · {formatShortDate(game.lastPlayedAt)}
              </span>
            </WorkLink>
          ))
        )}
      </div>
    </section>
  );
}

function Tonight({ data, onNext }: { data: DashboardResult; onNext: () => void }) {
  const title = data.hasGames ? '今晚玩什么' : '今晚看点、听点什么';
  return (
    <section className="dash-tonight" aria-labelledby="tonight-title">
      <div className="dash-section-heading">
        <h2 id="tonight-title">
          <Flame size={16} />
          {title}
        </h2>
        <button
          className="button button-ghost button-sm"
          onClick={onNext}
          disabled={!data.recommendations.length}
        >
          <RefreshCw size={14} />
          换一批
        </button>
      </div>
      {data.recommendations.length ? (
        <ol className="tonight-list" data-testid="recommendations">
          {data.recommendations.map(({ game, reasons }) => (
            <li key={game.id}>
              <WorkLink game={game} className="tonight-item">
                <GameCover game={game} compact />
                <span>
                  <span className="tonight-title">{game.title}</span>
                  <span className="tonight-reason">{reasons.join(' · ')}</span>
                </span>
              </WorkLink>
            </li>
          ))}
        </ol>
      ) : (
        <p className="section-empty">这个范围里没有未开始或搁置的作品。</p>
      )}
      <p className="dash-footnote">
        规则：从未开始或搁置的{data.hasGames ? '游戏' : '作品'}
        中挑选，本机可用与收藏优先；同一批次结果固定，可复现。
      </p>
    </section>
  );
}

const backlogOrder: GameStatus[] = ['unplayed', 'playing', 'paused', 'completed'];

function Backlog({ data }: { data: DashboardResult }) {
  const total = backlogOrder.reduce((sum, status) => sum + data.backlog[status], 0);
  const scoped = scopeLibraryFilters(data.scope);
  return (
    <section className="dash-module" aria-labelledby="backlog-title">
      <h2 id="backlog-title">
        <Hourglass size={15} />
        {data.hasGames ? '游戏待玩清单' : '待体验清单'}
      </h2>
      <p className="dash-module-note">
        {data.hasGames
          ? '仅统计游戏；按你标记的状态。'
          : '统计 DLsite 非游戏作品，按你标记的状态。'}
      </p>
      <div className="backlog-bar" aria-hidden="true">
        {backlogOrder.map((status) => (
          <span
            key={status}
            className={`status-${status}`}
            style={{
              flexGrow: data.backlog[status] || 0,
              display: data.backlog[status] ? undefined : 'none',
            }}
          />
        ))}
      </div>
      <ul className="backlog-list">
        {backlogOrder.map((status) => (
          <li key={status}>
            <AppLink
              to={libraryHrefFor({
                ...scoped,
                ...(data.hasGames ? { kind: 'game' as const } : {}),
                status,
              })}
            >
              <span className={`status-label status-${status}`}>
                <i className="status-dot" />
                {statusLabels[status]}
              </span>
              <strong>{data.backlog[status].toLocaleString('zh-CN')}</strong>
              <span className="backlog-share">
                {total ? Math.round((data.backlog[status] / total) * 100) : 0}%
              </span>
            </AppLink>
          </li>
        ))}
      </ul>
    </section>
  );
}

function MostPlayed({ data }: { data: DashboardResult }) {
  const max = data.mostPlayed[0]?.playtimeMinutes ?? 1;
  return (
    <section className="dash-module" aria-labelledby="most-played-title">
      <h2 id="most-played-title">
        <Flame size={15} />
        最常玩
      </h2>
      <p className="dash-module-note">按有记录的累计游玩时长排序。</p>
      {data.mostPlayed.length ? (
        <ol className="most-played">
          {data.mostPlayed.map((game, index) => (
            <li key={game.id}>
              <span className="rank">{index + 1}</span>
              <WorkLink game={game} className="most-played-title">
                {game.title}
              </WorkLink>
              <span className="most-played-hours">{hours(game.playtimeMinutes ?? 0)} 小时</span>
              <span className="most-played-bar" aria-hidden="true">
                <span style={{ width: `${((game.playtimeMinutes ?? 0) / max) * 100}%` }} />
              </span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="section-empty">这个范围没有可用的游玩时长记录。</p>
      )}
    </section>
  );
}

function Sources({ data }: { data: DashboardResult }) {
  const realSources = useRealSources().data;
  const running = useDownloads().activeCount + useExtractions().activeCount;
  const { openSources, openTasks } = useShell();
  return (
    <section className="dash-module dash-sources" aria-labelledby="sources-title">
      <h2 id="sources-title">
        <PlugZap size={15} />
        来源与同步
      </h2>
      <p className="dash-module-note">作品资料来自你手动触发的同步。</p>
      <ul className="source-list">
        {(['steam', 'dlsite'] as const).map((platform) => (
          <li key={platform} data-source={platform}>
            <span className={`source-mark source-${platform}`} aria-hidden="true">
              {platformLabels[platform].slice(0, 1)}
            </span>
            <span className="source-name">
              <AppLink to={libraryHrefFor({ platform })}>{platformLabels[platform]}</AppLink>
              <small>
                {data.sources[platform].works.toLocaleString('zh-CN')} 部 · 本机{' '}
                {data.sources[platform].local.toLocaleString('zh-CN')}
              </small>
            </span>
            <ConnectionBadge
              state={realConnectionState(realSources?.find((source) => source.id === platform))}
            />
          </li>
        ))}
      </ul>
      <button className="button button-secondary button-sm" onClick={openSources}>
        管理来源连接
      </button>
      <div className="queue-summary" data-testid="queue-summary">
        <Download size={14} />
        <span>{running ? `下载队列：${running} 个进行中` : '下载队列为空'}</span>
        <button className="link-button" onClick={openTasks}>
          查看
        </button>
      </div>
    </section>
  );
}

function DashboardSkeleton() {
  return (
    <div className="dashboard-page" role="status" aria-label="正在整理首页">
      <p className="sr-only">正在整理首页</p>
      <div className="dash-hero skeleton-hero">
        <div className="detail-frame dash-hero-inner">
          <span className="skeleton-block" style={{ width: 220, height: 44 }} />
          <div className="dash-feature">
            <div className="dash-feature-cover">
              <div className="skeleton-cover" />
            </div>
            <div className="dash-feature-copy">
              <span className="skeleton-block" style={{ width: 180, height: 12 }} />
              <span
                className="skeleton-block"
                style={{ width: '50%', height: 36, marginTop: 16 }}
              />
              <span className="skeleton-block" style={{ width: 240, height: 40, marginTop: 20 }} />
            </div>
          </div>
          <div className="dash-stats">
            {Array.from({ length: 4 }, (_, index) => (
              <span key={index} className="skeleton-block" style={{ height: 52 }} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export function DashboardPage() {
  const { isTestLibrary } = useWorkspace();
  const [scope, setScopeState] = useState<DashboardScope>(readScope);
  const [featuredIndex, setFeaturedIndex] = useState(0);
  const [batch, setBatch] = useState(0);
  const query = useDashboard(scope, batch);
  const data = query.data;

  useEffect(() => {
    document.title = '首页 · Library Atlas';
  }, []);
  const setScope = (next: DashboardScope) => {
    setScopeState(next);
    setFeaturedIndex(0);
    setBatch(0);
    const url = new URL(window.location.href);
    if (next === 'all') url.searchParams.delete('scope');
    else url.searchParams.set('scope', next);
    patchHistoryState({}, `${url.pathname}${url.search}`);
  };

  if (query.isPending) return <DashboardSkeleton />;
  if (!data)
    return (
      <main className="dashboard-page dash-feedback" data-testid="dashboard-failure">
        <ReadFailure error={query.error ?? new Error()} onRetry={() => void query.refetch()} />
      </main>
    );
  if (data.sources.steam.works + data.sources.dlsite.works === 0)
    return (
      <main className="dashboard-page dash-feedback" data-testid="dashboard-empty">
        <RealLibraryEmpty />
      </main>
    );

  const featured = data.featured.length
    ? data.featured[featuredIndex % data.featured.length]!
    : null;
  const libraryAll = libraryHrefFor(scopeLibraryFilters(scope));
  return (
    <main
      className="dashboard-page"
      data-testid="dashboard"
      data-scope={scope}
      // The previous range stays on screen, dimmed, until the new one aggregates.
      data-ready={!query.isPlaceholderData}
      aria-busy={query.isPlaceholderData}
    >
      <section className="dash-hero" aria-labelledby="dash-title">
        {featured ? (
          <HeroBackdrop key={featured.id} game={featured} />
        ) : (
          <div className="hero-backdrop hero-fallback" />
        )}
        <div className="hero-scrim" aria-hidden="true" />
        <div className="detail-frame dash-hero-inner">
          <div className="dash-topline">
            <div>
              <span className="eyebrow">WELCOME BACK</span>
              <h1 id="dash-title">欢迎回来</h1>
              <p>
                你的收藏共 {data.sources.steam.works + data.sources.dlsite.works} 部作品
                {isTestLibrary && <span className="sample-chip">测试数据 · 合成样本</span>}
              </p>
            </div>
            <ScopeSwitch scope={scope} onChange={setScope} />
          </div>
          {featured ? (
            <Featured
              game={featured}
              canCycle={data.featured.length > 1}
              onNext={() => setFeaturedIndex((index) => index + 1)}
            />
          ) : (
            <div className="dash-feature dash-feature-empty">
              <p>这个范围暂时没有可展示的作品。</p>
            </div>
          )}
          <Stats data={data} />
        </div>
      </section>

      {data.totals.works === 0 ? (
        <div className="detail-frame">
          <FeedbackState
            kind="empty"
            icon={Shapes}
            title="这个范围还没有作品"
            description="换一个范围，或回到全部作品。"
            action="查看全部作品"
            onAction={() => setScope('all')}
          />
        </div>
      ) : (
        <div className="detail-frame dash-body">
          <div className="dash-main-grid">
            <RecentRow data={data} />
            <Tonight data={data} onNext={() => setBatch((value) => value + 1)} />
          </div>
          <div className="dash-insights">
            {data.hasGames && <MostPlayed data={data} />}
            {data.hasGames && (
              <section className="dash-module" aria-labelledby="playtime-title">
                <h2 id="playtime-title">
                  <Timer size={15} />
                  游玩时长分布
                </h2>
                <p className="dash-module-note">
                  横轴单位：小时。仅含时长大于 0 的游戏；
                  {data.totals.unstartedGames.toLocaleString('zh-CN')} 款未开始、
                  {data.totals.unknownPlaytimeGames.toLocaleString('zh-CN')} 款无记录未计入。
                </p>
                {data.totals.playedGames ? (
                  <Suspense fallback={chartFallback}>
                    <PlaytimeChart buckets={data.playtimeBuckets} />
                  </Suspense>
                ) : (
                  <p className="section-empty">该范围没有可用的游玩时长。</p>
                )}
              </section>
            )}
            {data.hasGames && (
              <section className="dash-module" aria-labelledby="genre-title">
                <h2 id="genre-title">
                  <Tags size={15} />
                  游戏类型
                </h2>
                <p className="dash-module-note">每款游戏计入一个主类型，计数互斥；显示前 8 类。</p>
                <Suspense fallback={chartFallback}>
                  <GenreChart genres={data.genres} />
                </Suspense>
              </section>
            )}
            <section className="dash-module" aria-labelledby="kinds-title">
              <h2 id="kinds-title">
                <LayoutGrid size={15} />
                作品构成
              </h2>
              <p className="dash-module-note">
                {scopeLabels[scope]}范围内各内容类型的数量，按来源区分。
              </p>
              <Suspense fallback={chartFallback}>
                <KindChart kinds={data.kinds} />
              </Suspense>
              <AppLink to={libraryAll} className="dash-more">
                在作品库中查看 {scopeLabels[scope]}
                <ArrowRight size={14} />
              </AppLink>
            </section>
            <Backlog data={data} />
            <Sources data={data} />
          </div>
        </div>
      )}
    </main>
  );
}
