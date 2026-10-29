import type { Game, LibraryFilters, LibraryResult } from './types';

const collator = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' });

export function isOrdinaryGame(game: Game): boolean {
  return game.visibility === 'normal';
}

/** Scope is applied before every search, facet and count, not just at rendering. */
export function selectLibrary(games: readonly Game[], filters: LibraryFilters): LibraryResult {
  const visible = games.filter(isOrdinaryGame);
  const search = filters.search.trim().normalize('NFKC').toLocaleLowerCase('zh-CN');
  const items = visible.filter((game) => {
    if (
      search &&
      !`${game.title} ${game.subtitle}`
        .normalize('NFKC')
        .toLocaleLowerCase('zh-CN')
        .includes(search)
    )
      return false;
    if (filters.genre !== 'all' && game.genre !== filters.genre) return false;
    if (filters.status !== 'all' && game.status !== filters.status) return false;
    if (filters.installed === 'installed' && !game.installed) return false;
    if (filters.installed === 'not-installed' && game.installed) return false;
    return !filters.favoritesOnly || game.favorite;
  });

  if (filters.sort !== 'curated') {
    items.sort((left, right) => {
      if (filters.sort === 'name-asc')
        return collator.compare(left.title, right.title) || left.id.localeCompare(right.id);
      if (filters.sort === 'name-desc')
        return collator.compare(right.title, left.title) || left.id.localeCompare(right.id);
      // Unknown playtime stays at the end in either direction.
      if (left.playtimeMinutes === null)
        return right.playtimeMinutes === null ? left.id.localeCompare(right.id) : 1;
      if (right.playtimeMinutes === null) return -1;
      const direction = filters.sort === 'playtime-asc' ? 1 : -1;
      return (
        direction * (left.playtimeMinutes - right.playtimeMinutes) ||
        left.id.localeCompare(right.id)
      );
    });
  }

  return {
    items,
    totalVisible: visible.length,
    filteredCount: items.length,
    genres: [...new Set(visible.map((game) => game.genre))].sort(collator.compare),
    installedCount: visible.filter((game) => game.installed).length,
    favoriteCount: visible.filter((game) => game.favorite).length,
    mode: 'demo',
  };
}
