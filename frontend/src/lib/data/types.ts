export type DemoSize = 1500 | 5000;
export type DemoScenario = 'normal' | 'empty' | 'loading' | 'error';
export type GameStatus = 'unplayed' | 'playing' | 'completed' | 'paused';
export type Visibility = 'normal' | 'hidden' | 'private' | 'quarantined';
export type LibrarySort = 'curated' | 'name-asc' | 'name-desc' | 'playtime-desc' | 'playtime-asc';

export interface Game {
  id: string;
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
  mode: 'demo';
}

export interface LibraryRequest {
  filters: LibraryFilters;
  scenario?: DemoScenario;
  signal?: AbortSignal;
}

/** Replace this boundary with the API source when backend work is authorized. */
export interface LibrarySource {
  readonly mode: 'demo' | 'real';
  list(request: LibraryRequest): Promise<LibraryResult>;
  toggleFavorite(id: string): Promise<void>;
}

export const defaultLibraryFilters: LibraryFilters = {
  search: '',
  genre: 'all',
  status: 'all',
  installed: 'all',
  favoritesOnly: false,
  sort: 'curated',
};
