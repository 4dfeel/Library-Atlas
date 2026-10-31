import type { Game, GameStatus, LibraryFilters, Platform, WorkKind } from './types';

/** Dashboard ranges. Each maps to one Library filter so "查看全部" stays consistent. */
export type DashboardScope = 'all' | 'games' | 'steam' | 'dlsite-games' | 'dlsite-media';
export const dashboardScopes: readonly DashboardScope[] = [
  'all',
  'games',
  'steam',
  'dlsite-games',
  'dlsite-media',
];

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

export interface Recommendation {
  game: Game;
  reasons: string[];
}

export interface PlaytimeBucket {
  label: string;
  count: number;
}

export interface DashboardRequest {
  scope: DashboardScope;
  batch?: number;
  signal?: AbortSignal;
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
    /** Non-game works with a usage record. */
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
