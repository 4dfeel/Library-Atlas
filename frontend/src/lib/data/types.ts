import type { DashboardRequest, DashboardResult } from './dashboard';

export type GameStatus = 'unplayed' | 'playing' | 'completed' | 'paused';
export type Visibility = 'normal' | 'hidden' | 'private' | 'quarantined';
export const librarySorts = [
  'curated',
  'name-asc',
  'name-desc',
  'playtime-desc',
  'playtime-asc',
  'added-desc',
  'added-asc',
  'maker-asc',
  'maker-desc',
  'genre-asc',
  'genre-desc',
  'rating-desc',
  'rating-asc',
  'release-desc',
  'release-asc',
  'size-desc',
  'size-asc',
] as const;
export type LibrarySort = (typeof librarySorts)[number];
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
  /** Atlas-internal stable ID; routes use it. */
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
   * differ per platform; downloaded never implies installed or launchable. `null`
   * means not known, which is never shown as absent.
   */
  installed: boolean | null;
  /** The folder this work is used from, in the real library. */
  copyId?: string | null;
  /** A game with its main program chosen. Whether it then runs is another matter. */
  launchable?: boolean;
  /** Game play time only; `null` when the source does not report it. */
  playtimeMinutes: number | null;
  favorite: boolean;
  visibility: Visibility;
  /** `remote`: a platform image served through Atlas's own cover address. */
  cover: { kind: 'procedural' | 'remote' | 'missing'; index: number; url?: string | null };
  addedAt: string;
  /** Last use: played for games; read, watched or listened for others. */
  lastPlayedAt: string | null;
  /** What Atlas could do with this work once the source is connected. */
  capabilities: WorkCapabilities;
  /** Minimal file identity; versions or language packs are not merged by title. */
  file: { version: string | null; sizeBytes: number | null } | null;
  /** Personal rating, 1–5. `null` means not rated. */
  rating?: number | null;
  /** The work's page on the source platform, when known. */
  sourceUrl?: string | null;
}

/** `null` means not known yet. */
export interface WorkCapabilities {
  /** Purchased files can be fetched directly (DLsite only). */
  download: boolean | null;
  /** Downloaded files are archives that need extracting. */
  extract: boolean | null;
  /** Only viewable in the platform's own reader; Atlas never bypasses this. */
  officialViewerOnly: boolean | null;
}

/** One file or part of a work. One work may have many; each part is not a work. */
export interface WorkFileInfo {
  id: string;
  label: string | null;
  version: string | null;
  language: string | null;
  partIndex: number | null;
  partCount: number | null;
  sizeBytes: number | null;
  format: string | null;
  availability: 'unknown' | 'downloadable' | 'viewer_only';
  downloadState: 'unknown' | 'not_downloaded' | 'downloaded';
  extractState: 'unknown' | 'not_applicable' | 'not_extracted' | 'extracted';
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
  /** One of the user's own collections, or `all`. */
  collection: string;
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
}

/** Achievement counts. `null` means not provided, never 0%. */
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
  /** Increases with every saved edit. */
  version?: number;
  /** Every known file or part. */
  files?: WorkFileInfo[];
}

/** Only these personal fields are writable; visibility and observations are not. */
export interface GameUpdate {
  status?: GameStatus;
  rating?: number | null;
  note?: string;
  favorite?: boolean;
  /** Refuse the save if the record changed since this version was read. */
  expectedVersion?: number;
}

export interface GameRequest {
  id: string;
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

/** What pages use. Lists are read in pages: see useLibraryCollection. */
export interface LibrarySource {
  dashboard(request: DashboardRequest): Promise<DashboardResult>;
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
  collection: 'all',
  sort: 'curated',
};
