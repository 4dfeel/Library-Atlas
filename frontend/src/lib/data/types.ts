export type DemoSize = 1500 | 5000;
export type DemoScenario = 'normal' | 'empty' | 'loading' | 'error';
export type GameStatus = 'unplayed' | 'playing' | 'completed' | 'paused';
export type Visibility = 'normal' | 'hidden' | 'private' | 'quarantined';
export type LibrarySort = 'curated' | 'name-asc' | 'name-desc' | 'playtime-desc' | 'playtime-asc';
/** Source platform of a library entry. Atlas data model is platform-neutral. */
export type Platform = 'steam' | 'dlsite';
/** What the work is; independent of genre. Steam entries are always games. */
export type WorkKind = 'game' | 'image' | 'video' | 'audio' | 'other';
export const workKinds: readonly WorkKind[] = ['game', 'image', 'video', 'audio', 'other'];

/**
 * One library entry (a "work") from any platform. The name predates multi-platform
 * support; it covers games, image, video, audio and other works alike.
 */
export interface Game {
  id: string;
  platform: Platform;
  kind: WorkKind;
  /** Studio, circle or brand. */
  maker: string;
  releaseDate: string | null;
  title: string;
  subtitle: string;
  genre: string;
  status: GameStatus;
  installed: boolean;
  playtimeMinutes: number | null;
  favorite: boolean;
  visibility: Visibility;
  cover: { kind: 'art' | 'procedural' | 'missing'; index: number };
  background: string | null;
  addedAt: string;
  lastPlayedAt: string | null;
}

export interface LibraryFilters {
  search: string;
  genre: string;
  status: GameStatus | 'all';
  installed: 'all' | 'installed' | 'not-installed';
  kind: WorkKind | 'all';
  platform: Platform | 'all';
  favoritesOnly: boolean;
  sort: LibrarySort;
}

export interface LibraryResult {
  items: Game[];
  totalVisible: number;
  filteredCount: number;
  genres: string[];
  installedCount: number;
  favoriteCount: number;
  /** Visible works per kind, before kind and other filters. */
  kindCounts: Record<WorkKind, number>;
  mode: 'demo';
}

export interface LibraryRequest {
  filters: LibraryFilters;
  scenario?: DemoScenario;
  signal?: AbortSignal;
}

/** Synthetic achievement counts. `null` means not provided, never 0%. */
export interface GameAchievements {
  unlocked: number;
  total: number;
}

/** Personal rating is a whole number of stars; `null` means not rated. */
export const ratingScale = { min: 1, max: 5 } as const;
export const noteMaxLength = 1000;

export interface GameDetail extends Game {
  /** `null` means no description was provided for this record. */
  description: string | null;
  tags: string[];
  categories: string[];
  achievements: GameAchievements | null;
  rating: number | null;
  note: string;
}

/** Only these personal fields are writable; visibility and observations are not. */
export interface GameUpdate {
  status?: GameStatus;
  rating?: number | null;
  note?: string;
  favorite?: boolean;
}

export interface GameRequest {
  id: string;
  scenario?: DemoScenario;
  signal?: AbortSignal;
}

/** Private, hidden, unconfirmed and absent IDs share this single error. */
export class GameUnavailableError extends Error {
  constructor() {
    super('作品暂不可用。');
    this.name = 'GameUnavailableError';
  }
}

export class GameUpdateError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'GameUpdateError';
  }
}

/** Replace this boundary with the API source when backend work is authorized. */
export interface LibrarySource {
  readonly mode: 'demo' | 'real';
  list(request: LibraryRequest): Promise<LibraryResult>;
  getGame(request: GameRequest): Promise<GameDetail>;
  updateGame(id: string, update: GameUpdate): Promise<GameDetail>;
  toggleFavorite(id: string): Promise<void>;
}

export const defaultLibraryFilters: LibraryFilters = {
  search: '',
  genre: 'all',
  status: 'all',
  installed: 'all',
  kind: 'all',
  platform: 'all',
  favoritesOnly: false,
  sort: 'curated',
};
