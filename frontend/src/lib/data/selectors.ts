import {
  workKinds,
  type Game,
  type LibraryFilters,
  type LibraryResult,
  type WorkKind,
} from './types';

const collator = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' });

export function isOrdinaryGame(game: Game): boolean {
  return game.visibility === 'normal';
}

const sortFields: Record<string, (game: Game) => string | number | null> = {
  name: (game) => game.title,
  playtime: (game) => game.playtimeMinutes,
  added: (game) => game.addedAt,
  maker: (game) => game.maker,
  genre: (game) => game.genre,
  rating: (game) => game.rating ?? null,
  release: (game) => game.releaseDate,
  size: (game) => game.file?.sizeBytes ?? null,
};

/** Scope is applied before every search, facet and count, not just at rendering. */
export function selectLibrary(games: readonly Game[], filters: LibraryFilters): LibraryResult {
  const visible = games.filter(isOrdinaryGame);
  const search = filters.search.trim().normalize('NFKC').toLocaleLowerCase('zh-CN');
  const items = visible.filter((game) => {
    if (
      search &&
      !`${game.title} ${game.subtitle} ${game.maker}`
        .normalize('NFKC')
        .toLocaleLowerCase('zh-CN')
        .includes(search)
    )
      return false;
    if (
      filters.kind === 'non-game'
        ? game.kind === 'game'
        : filters.kind !== 'all' && game.kind !== filters.kind
    )
      return false;
    if (filters.platform !== 'all' && game.platform !== filters.platform) return false;
    if (filters.genre !== 'all' && game.genre !== filters.genre) return false;
    if (filters.status !== 'all' && game.status !== filters.status) return false;
    if (filters.installed === 'installed' && !game.installed) return false;
    if (filters.installed === 'not-installed' && game.installed) return false;
    return !filters.favoritesOnly || game.favorite;
  });

  if (filters.sort !== 'curated') {
    const [field, direction] = filters.sort.split('-') as [string, 'asc' | 'desc'];
    const read = sortFields[field]!;
    const sign = direction === 'desc' ? -1 : 1;
    items.sort((left, right) => {
      const a = read(left);
      const b = read(right);
      // Unknown values stay at the end in either direction.
      if (a === null) return b === null ? left.id.localeCompare(right.id) : 1;
      if (b === null) return -1;
      const order =
        typeof a === 'number' && typeof b === 'number'
          ? a - b
          : collator.compare(String(a), String(b));
      return sign * order || left.id.localeCompare(right.id);
    });
  }

  return {
    items,
    totalVisible: visible.length,
    filteredCount: items.length,
    // Genres follow the selected work kind so the dropdown never offers empty choices.
    genres: [
      ...new Set(
        visible
          .filter((game) =>
            filters.kind === 'non-game'
              ? game.kind !== 'game'
              : filters.kind === 'all' || game.kind === filters.kind,
          )
          .map((game) => game.genre),
      ),
    ].sort(collator.compare),
    installedCount: visible.filter((game) => game.installed).length,
    favoriteCount: visible.filter((game) => game.favorite).length,
    kindCounts: Object.fromEntries(
      workKinds.map((kind) => [kind, visible.filter((game) => game.kind === kind).length]),
    ) as Record<WorkKind, number>,
  };
}
