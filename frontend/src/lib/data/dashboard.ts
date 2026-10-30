import { isOrdinaryGame } from './selectors';
import {
  workKinds,
  type Game,
  type GameStatus,
  type LibraryFilters,
  type Platform,
  type WorkKind,
} from './types';

/** Dashboard ranges. Each maps to one Library filter so "查看全部" stays consistent. */
export type DashboardScope = 'all' | 'games' | 'steam' | 'dlsite-games' | 'dlsite-media';
export const dashboardScopes: readonly DashboardScope[] = [
  'all',
  'games',
  'steam',
  'dlsite-games',
  'dlsite-media',
];

export function inScope(game: Game, scope: DashboardScope): boolean {
  switch (scope) {
    case 'all':
      return true;
    case 'games':
      return game.kind === 'game';
    case 'steam':
      return game.platform === 'steam';
    case 'dlsite-games':
      return game.platform === 'dlsite' && game.kind === 'game';
    case 'dlsite-media':
      return game.platform === 'dlsite' && game.kind !== 'game';
  }
}

/** Library filters that list exactly the works counted in a scope. */
export function scopeLibraryFilters(scope: DashboardScope): Partial<LibraryFilters> {
  switch (scope) {
    case 'all':
      return {};
    case 'games':
      return { kind: 'game' };
    case 'steam':
      return { platform: 'steam' };
    case 'dlsite-games':
      return { platform: 'dlsite', kind: 'game' };
    case 'dlsite-media':
      return { platform: 'dlsite', kind: 'non-game' };
  }
}

/** Fixed reference date for reproducible picks; never the wall clock. */
export const demoReferenceDate = '2026-10-30';

export interface Recommendation {
  game: Game;
  reasons: string[];
}

export interface PlaytimeBucket {
  label: string;
  count: number;
}

export interface DashboardResult {
  scope: DashboardScope;
  /** True when the scope contains games; game-only modules render only then. */
  hasGames: boolean;
  totals: {
    works: number;
    games: number;
    /** Games with a recorded play time above zero. */
    playedGames: number;
    /** Games the user marked 未开始; independent of missing records. */
    unstartedGames: number;
    /** Games whose source reports no play time at all. */
    unknownPlaytimeGames: number;
    /** Sum over games with a record only; never includes audio or video. */
    playtimeMinutes: number;
    nonGames: number;
    /** Non-game works with a demo usage record. */
    usedNonGames: number;
    local: number;
    favorites: number;
  };
  /** Up to 8 candidates with art and a backdrop; the page cycles through them. */
  featured: Game[];
  recent: Game[];
  mostPlayed: Game[];
  recommendations: Recommendation[];
  /** Games with play time > 0 only; zero and unknown are reported separately. */
  playtimeBuckets: PlaytimeBucket[];
  genres: { genre: string; count: number }[];
  kinds: { kind: WorkKind; steam: number; dlsite: number }[];
  /** Status counts over games (game scopes) or over works (DLsite media scope). */
  backlog: Record<GameStatus, number>;
  sources: Record<Platform, { works: number; games: number; local: number }>;
}

/** FNV-1a over a string; stable across runs for reproducible picks. */
function hash(text: string): number {
  let value = 0x811c9dc5;
  for (let index = 0; index < text.length; index++) {
    value ^= text.charCodeAt(index);
    value = Math.imul(value, 0x01000193);
  }
  return (value >>> 0) / 4294967296;
}

const byRecent = (left: Game, right: Game) =>
  (right.lastPlayedAt ?? '').localeCompare(left.lastPlayedAt ?? '') ||
  left.id.localeCompare(right.id);

function recommend(pool: Game[], batch: number): Recommendation[] {
  const candidates = pool.filter((game) => game.status === 'unplayed' || game.status === 'paused');
  const seed = `${demoReferenceDate}:${batch}`;
  return candidates
    .map((game) => {
      const reasons: string[] = [];
      let score = hash(`${seed}:${game.id}`);
      if (game.installed) {
        score += 1.2;
        reasons.push(game.platform === 'steam' ? '已安装' : '已下载');
      }
      if (game.favorite) {
        score += 1;
        reasons.push('你收藏过');
      }
      reasons.push(game.status === 'paused' ? '上次搁置，可以接着来' : '还没开始');
      return { game, reasons, score };
    })
    .sort((left, right) => right.score - left.score || left.game.id.localeCompare(right.game.id))
    .slice(0, 3)
    .map(({ game, reasons }) => ({ game, reasons }));
}

/**
 * Pure aggregation over one consistent snapshot. Privacy scope is applied first,
 * then the dashboard range; every count, pick and chart derives from that set.
 */
export function selectDashboard(
  all: readonly Game[],
  scope: DashboardScope,
  batch = 0,
): DashboardResult {
  const visible = all.filter(isOrdinaryGame);
  const works = visible.filter((game) => inScope(game, scope));
  const games = works.filter((game) => game.kind === 'game');
  const nonGames = works.filter((game) => game.kind !== 'game');
  const hasGames = scope !== 'dlsite-media';
  const withPlay = games.filter((game) => (game.playtimeMinutes ?? 0) > 0);

  const featuredPool = works
    .filter((game) => game.cover.kind !== 'missing' && game.background)
    .sort(
      (left, right) =>
        Number(right.cover.kind === 'art') - Number(left.cover.kind === 'art') ||
        Number(right.favorite) - Number(left.favorite) ||
        byRecent(left, right),
    )
    .slice(0, 8);

  const bucketEdges: [string, number, number][] = [
    ['< 1 小时', 0, 60],
    ['1–10 小时', 60, 600],
    ['10–50 小时', 600, 3000],
    ['50–100 小时', 3000, 6000],
    ['100 小时以上', 6000, Number.POSITIVE_INFINITY],
  ];
  const genreCounts = new Map<string, number>();
  for (const game of games) genreCounts.set(game.genre, (genreCounts.get(game.genre) ?? 0) + 1);
  const backlogPool = hasGames ? games : works;
  const backlog: Record<GameStatus, number> = { unplayed: 0, playing: 0, completed: 0, paused: 0 };
  for (const game of backlogPool) backlog[game.status]++;
  const source = (platform: Platform) => {
    const entries = visible.filter((game) => game.platform === platform);
    return {
      works: entries.length,
      games: entries.filter((game) => game.kind === 'game').length,
      local: entries.filter((game) => game.installed).length,
    };
  };

  return {
    scope,
    hasGames,
    totals: {
      works: works.length,
      games: games.length,
      playedGames: withPlay.length,
      unstartedGames: games.filter((game) => game.status === 'unplayed').length,
      unknownPlaytimeGames: games.filter((game) => game.playtimeMinutes === null).length,
      playtimeMinutes: games.reduce((sum, game) => sum + (game.playtimeMinutes ?? 0), 0),
      nonGames: nonGames.length,
      usedNonGames: nonGames.filter((game) => game.lastPlayedAt !== null).length,
      local: works.filter((game) => game.installed).length,
      favorites: works.filter((game) => game.favorite).length,
    },
    featured: featuredPool,
    recent: works
      .filter((game) => game.lastPlayedAt !== null)
      .sort(byRecent)
      .slice(0, 12),
    mostPlayed: [...withPlay]
      .sort(
        (left, right) =>
          (right.playtimeMinutes ?? 0) - (left.playtimeMinutes ?? 0) ||
          left.id.localeCompare(right.id),
      )
      .slice(0, 5),
    recommendations: recommend(hasGames ? games : nonGames, batch),
    playtimeBuckets: bucketEdges.map(([label, min, max]) => ({
      label,
      count: withPlay.filter((game) => game.playtimeMinutes! >= min && game.playtimeMinutes! < max)
        .length,
    })),
    genres: [...genreCounts]
      .map(([genre, count]) => ({ genre, count }))
      .sort((left, right) => right.count - left.count || left.genre.localeCompare(right.genre)),
    kinds: workKinds.map((kind) => ({
      kind,
      steam: works.filter((game) => game.kind === kind && game.platform === 'steam').length,
      dlsite: works.filter((game) => game.kind === kind && game.platform === 'dlsite').length,
    })),
    backlog,
    sources: { steam: source('steam'), dlsite: source('dlsite') },
  };
}
