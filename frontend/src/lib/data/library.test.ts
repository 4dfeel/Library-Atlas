import { describe, expect, it } from 'vitest';
import { getCoverSource } from './covers';
import { DemoLibrarySource } from './demo-source';
import { generateDemoGames } from './generator';
import { selectLibrary } from './selectors';
import { defaultLibraryFilters, type Game } from './types';

const filters = { ...defaultLibraryFilters };

describe('deterministic isolated demo fixtures', () => {
  it('reproduces the same first 1500 records across both scale settings', () => {
    const normal = generateDemoGames(1500);
    expect(normal).toHaveLength(1500);
    expect(generateDemoGames(5000).slice(0, 1500)).toEqual(normal);
    expect(new Set(normal.map((game) => game.id)).size).toBe(1500);
  });

  it('provides art, missing, procedural, absent background and multilingual long titles', () => {
    const games = generateDemoGames(1500);
    expect(games.slice(0, 24).every((game) => game.cover.kind === 'art')).toBe(true);
    const missingRatio =
      games.filter((game) => game.cover.kind === 'missing').length / games.length;
    expect(missingRatio).toBeGreaterThan(0.08);
    expect(missingRatio).toBeLessThan(0.1);
    expect(games.some((game) => game.background === null)).toBe(true);
    expect(games.some((game) => game.title.includes('遠い銀河'))).toBe(true);
    expect(games.some((game) => game.title.length > 70)).toBe(true);
  });
});

describe('ordinary selection privacy boundary', () => {
  const games = generateDemoGames(1500);

  it('excludes private, hidden and unknown visibility before results and counts', () => {
    const result = selectLibrary(games, filters);
    expect(result.items.every((game) => game.visibility === 'normal')).toBe(true);
    expect(result.totalVisible).toBe(games.filter((game) => game.visibility === 'normal').length);
    expect(JSON.stringify(result)).not.toContain('PRIVATE_SENTINEL');
    expect(result.filteredCount).toBe(result.totalVisible);
  });

  it('cannot find a private sentinel by exact title or through facets and aggregates', () => {
    const privateGame = games.find((game) => game.visibility === 'private');
    expect(privateGame).toBeDefined();
    const result = selectLibrary(games, { ...filters, search: privateGame!.title });
    expect(result.items).toEqual([]);
    expect(result.filteredCount).toBe(0);
    expect(JSON.stringify(result)).not.toContain('PRIVATE_SENTINEL');
    const privateOnly: Game = {
      ...privateGame!,
      genre: 'Secret Genre',
      installed: true,
      favorite: true,
    };
    const isolated = selectLibrary([privateOnly], filters);
    expect(isolated).toMatchObject({
      items: [],
      totalVisible: 0,
      genres: [],
      installedCount: 0,
      favoriteCount: 0,
    });
  });

  it('combines name, genre, status, installation and favorite filters', () => {
    const game = games[0]!;
    const result = selectLibrary(games, {
      ...filters,
      search: game.title,
      genre: game.genre,
      status: game.status,
      installed: 'installed',
      favoritesOnly: true,
    });
    expect(result.items.map((entry) => entry.id)).toEqual([game.id]);
    expect(
      selectLibrary(games, { ...filters, search: game.title, installed: 'not-installed' }).items,
    ).toEqual([]);
  });

  it('normalizes full-width search input and matches English subtitles', () => {
    expect(selectLibrary(games, { ...filters, search: 'ＡＳＴＲＡＬ' }).items[0]?.id).toBe(
      games[0]?.id,
    );
    expect(selectLibrary(games, { ...filters, search: '   ' }).filteredCount).toBe(
      selectLibrary(games, filters).totalVisible,
    );
  });

  it('sorts time consistently without treating unknown as zero', () => {
    for (const sort of ['playtime-desc', 'playtime-asc'] as const) {
      const result = selectLibrary(games, { ...filters, sort });
      const values = result.items.flatMap((game) =>
        game.playtimeMinutes === null ? [] : [game.playtimeMinutes],
      );
      expect(values).toEqual(
        [...values].sort((left, right) => (sort === 'playtime-desc' ? right - left : left - right)),
      );
      expect(result.items.at(-1)?.playtimeMinutes).toBeNull();
    }
  });

  it('reverses name ordering while keeping stable IDs for ties', () => {
    const asc = selectLibrary(games, { ...filters, sort: 'name-asc' });
    const desc = selectLibrary(games, { ...filters, sort: 'name-desc' });
    expect(asc.items.map((game) => game.id)).toEqual(desc.items.map((game) => game.id).reverse());
  });
});

describe('demo source behavior', () => {
  it('toggles a public favorite for this session and keeps separate source instances isolated', async () => {
    const source = new DemoLibrarySource(1500);
    const independent = new DemoLibrarySource(1500);
    const before = await source.list({ filters });
    const first = before.items[0]!;
    await source.toggleFavorite(first.id);
    const after = await source.list({ filters });
    expect(after.items[0]?.favorite).toBe(!first.favorite);
    expect(after.favoriteCount).toBe(before.favoriteCount - 1);
    expect((await independent.list({ filters })).items[0]?.favorite).toBe(first.favorite);
    await source.toggleFavorite(first.id);
    expect((await source.list({ filters })).items[0]?.favorite).toBe(first.favorite);
  });

  it('rejects writes to private and absent IDs without exposing titles', async () => {
    const source = new DemoLibrarySource(1500);
    const privateGame = generateDemoGames(1500).find((game) => game.visibility === 'private')!;
    await expect(source.toggleFavorite(privateGame.id)).rejects.toThrow('游戏暂不可用。');
    await expect(source.toggleFavorite('unknown')).rejects.toThrow('游戏暂不可用。');
  });

  it('supports explicit empty and error previews', async () => {
    const source = new DemoLibrarySource(1500);
    expect(await source.list({ filters, scenario: 'empty' })).toMatchObject({
      items: [],
      totalVisible: 0,
      filteredCount: 0,
    });
    await expect(source.list({ filters, scenario: 'error' })).rejects.toThrow(
      '演示数据暂时无法读取',
    );
  });

  it('aborts in-flight loading previews instead of retaining stale work', async () => {
    const controller = new AbortController();
    const request = new DemoLibrarySource(1500).list({
      filters,
      scenario: 'loading',
      signal: controller.signal,
    });
    controller.abort();
    await expect(request).rejects.toMatchObject({ name: 'AbortError' });
  });
});

describe('on-demand local cover selection', () => {
  const games = generateDemoGames(1500);

  it('uses local SVG art or procedural SVG without external hosts', () => {
    expect(getCoverSource(games[0]!)).toBe('/demo/covers/cover-01.svg');
    const procedural = games.find(
      (game) => game.cover.kind === 'procedural' && game.visibility === 'normal',
    )!;
    expect(getCoverSource(procedural)).toMatch(/^data:image\/svg\+xml/);
    expect(getCoverSource(procedural)).toBe(getCoverSource(procedural));
  });

  it('does not produce an image URL for missing or nonordinary games', () => {
    const missing = games.find((game) => game.cover.kind === 'missing')!;
    const privateGame = games.find((game) => game.visibility === 'private')!;
    expect(getCoverSource(missing)).toBeNull();
    expect(getCoverSource(privateGame)).toBeNull();
  });

  it('lays out escaped title/subtitle as SVG text, never executable markup', () => {
    const game: Game = {
      ...games[25]!,
      title: '星海 <&> "引号"',
      subtitle: '<script>alert(1)</script> & "notes"',
      cover: { kind: 'procedural', index: 25 },
    };
    const source = getCoverSource(game)!;
    const svg = decodeURIComponent(source.slice(source.indexOf(',') + 1));
    const document = new DOMParser().parseFromString(svg, 'image/svg+xml');
    expect(document.querySelector('parsererror')).toBeNull();
    expect(document.querySelector('script')).toBeNull();
    expect(document.querySelector('tspan')?.textContent).toBe(game.title);
    expect(document.documentElement.textContent).toContain(game.subtitle);
    expect(document.querySelectorAll('tspan').length).toBeLessThanOrEqual(2);
    expect(getCoverSource({ ...game, visibility: 'private' })).toBeNull();
  });
});
