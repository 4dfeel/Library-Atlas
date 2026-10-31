import {
  defaultLibraryFilters,
  librarySorts,
  workKinds,
  type LibraryFilters,
  type LibrarySort,
} from '@/lib/data';
import type { ViewMode } from './game-collection';

/**
 * Library query state lives in the URL so back/forward, refresh and copied links
 * restore search, filters, sort and view. Unknown values fall back to defaults.
 */
export interface LibraryUrlState {
  filters: LibraryFilters;
  view: ViewMode;
}

const statuses = new Set(['all', 'unplayed', 'playing', 'completed', 'paused']);
const installed = new Set(['all', 'installed', 'not-installed']);
const kinds = new Set(['all', 'non-game', ...workKinds]);
const platforms = new Set(['all', 'steam', 'dlsite']);
const sorts = new Set<LibrarySort>(librarySorts);

export function parseLibraryUrl(search: string): LibraryUrlState {
  const params = new URLSearchParams(search);
  const status = params.get('status') ?? 'all';
  const install = params.get('installed') ?? 'all';
  const sort = (params.get('sort') ?? 'curated') as LibrarySort;
  const kind = params.get('kind') ?? 'all';
  const platform = params.get('platform') ?? 'all';
  return {
    filters: {
      search: (params.get('q') ?? '').slice(0, 200),
      genre: params.get('genre') || defaultLibraryFilters.genre,
      status: statuses.has(status) ? (status as LibraryFilters['status']) : 'all',
      installed: installed.has(install) ? (install as LibraryFilters['installed']) : 'all',
      kind: kinds.has(kind) ? (kind as LibraryFilters['kind']) : 'all',
      platform: platforms.has(platform) ? (platform as LibraryFilters['platform']) : 'all',
      favoritesOnly: params.get('fav') === '1',
      collection: (params.get('collection') ?? '').slice(0, 64) || 'all',
      sort: sorts.has(sort) ? sort : 'curated',
    },
    view: params.get('view') === 'list' ? 'list' : 'grid',
  };
}

/** Keeps unrelated parameters and writes only non-defaults. */
export function libraryUrl(current: string, { filters, view }: LibraryUrlState): string {
  const url = new URL(current);
  const params = url.searchParams;
  const set = (key: string, value: string, fallback: string) =>
    value === fallback ? params.delete(key) : params.set(key, value);
  set('q', filters.search.trim(), '');
  set('genre', filters.genre, 'all');
  set('status', filters.status, 'all');
  set('installed', filters.installed, 'all');
  set('kind', filters.kind, 'all');
  set('platform', filters.platform, 'all');
  set('fav', filters.favoritesOnly ? '1' : '0', '0');
  set('collection', filters.collection, 'all');
  set('sort', filters.sort, 'curated');
  set('view', view, 'grid');
  return `${url.pathname}${params.size ? `?${params}` : ''}`;
}

/** A Library link pre-filtered by the given values (used by Dashboard entries). */
export function libraryHrefFor(filters: Partial<LibraryFilters>): string {
  const params = new URLSearchParams();
  if (filters.kind && filters.kind !== 'all') params.set('kind', filters.kind);
  if (filters.platform && filters.platform !== 'all') params.set('platform', filters.platform);
  if (filters.status && filters.status !== 'all') params.set('status', filters.status);
  if (filters.genre && filters.genre !== 'all') params.set('genre', filters.genre);
  if (filters.installed && filters.installed !== 'all') params.set('installed', filters.installed);
  if (filters.sort && filters.sort !== 'curated') params.set('sort', filters.sort);
  return `/library${params.size ? `?${params}` : ''}`;
}
