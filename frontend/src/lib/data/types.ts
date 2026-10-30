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
  /** Atlas-internal stable ID; routes and demo edits use it. */
  id: string;
  platform: Platform;
  /** ID inside the source platform. Identity is (platform, sourceId), never sourceId alone. */
  sourceId: string;
  kind: WorkKind;
  /** Studio, circle or brand. */
  maker: string;
  releaseDate: string | null;
  title: string;
  subtitle: string;
  /** Genre or theme tag (RPG, 有声剧…); never the content kind. */
  genre: string;
  status: GameStatus;
  /**
   * Locally available: an installed Steam game, or downloaded DLsite files. Labels
   * differ per platform; downloaded never implies installed or launchable.
   */
  installed: boolean;
  /** Game play time only; `null` when the source does not report it. */
  playtimeMinutes: number | null;
  favorite: boolean;
  visibility: Visibility;
  cover: { kind: 'art' | 'procedural' | 'missing'; index: number };
  background: string | null;
  addedAt: string;
  /** Last use: played for games; read, watched or listened for others. Demo record. */
  lastPlayedAt: string | null;
  /** What Atlas could do with this work once the source is connected. */
  capabilities: WorkCapabilities;
  /** Minimal file identity; versions or language packs are not merged by title. */
  file: { version: string; sizeBytes: number | null } | null;
}

export interface WorkCapabilities {
  /** Purchased files can be fetched directly (DLsite only, demo). */
  download: boolean;
  /** Downloaded files are archives that need extracting. */
  extract: boolean;
  /** Only viewable in the platform's own reader; Atlas never bypasses this. */
  officialViewerOnly: boolean;
}

export interface LibraryFilters {
  search: string;
  genre: string;
  status: GameStatus | 'all';
  installed: 'all' | 'installed' | 'not-installed';
  /** `non-game` lists every kind except games (dashboard DLsite media range). */
  kind: WorkKind | 'all' | 'non-game';
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
