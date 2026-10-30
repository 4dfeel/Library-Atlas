import { describe, expect, it } from 'vitest';
import { availabilityLabel, workMeta } from '@/lib/utils';
import { createMemoryEditStore } from './demo-edits';
import { DemoLibrarySource } from './demo-source';
import { generateDemoGames } from './generator';
import { selectLibrary } from './selectors';
import { defaultLibraryFilters, workKinds } from './types';

const games = generateDemoGames(1500);
const filters = { ...defaultLibraryFilters };

describe('multi-platform works', () => {
  it('mixes Steam games with DLsite works of every kind', () => {
    expect(games.slice(0, 24).every((game) => game.platform === 'steam')).toBe(true);
    expect(games.every((game) => game.platform === 'dlsite' || game.kind === 'game')).toBe(true);
    for (const kind of workKinds)
      expect(games.some((game) => game.platform === 'dlsite' && game.kind === kind)).toBe(true);
    expect(
      games
        .filter((game) => game.platform === 'dlsite')
        .every((game) => game.playtimeMinutes === null),
    ).toBe(true);
  });

  it('filters by kind and platform and counts kinds after the privacy scope', () => {
    const all = selectLibrary(games, filters);
    const ordinary = games.filter((game) => game.visibility === 'normal');
    for (const kind of workKinds) {
      const result = selectLibrary(games, { ...filters, kind });
      expect(result.items.every((game) => game.kind === kind)).toBe(true);
      expect(result.filteredCount).toBe(all.kindCounts[kind]);
      expect(all.kindCounts[kind]).toBe(ordinary.filter((game) => game.kind === kind).length);
    }
    const audio = selectLibrary(games, { ...filters, kind: 'audio' });
    expect(audio.genres.every((genre) => ['有声剧', '环境音'].includes(genre))).toBe(true);
    const dlsite = selectLibrary(games, { ...filters, platform: 'dlsite' });
    expect(dlsite.items.every((game) => game.platform === 'dlsite')).toBe(true);
    expect(selectLibrary(games, { ...filters, platform: 'steam', kind: 'audio' }).items).toEqual(
      [],
    );
    expect(
      selectLibrary(games, { ...filters, search: 'Lumen Works' }).filteredCount,
    ).toBeGreaterThan(0);
  });

  it('never invents play time or achievements for DLsite works', async () => {
    const source = new DemoLibrarySource(1500, { store: createMemoryEditStore() });
    const work = await source.getGame({ id: 'demo-00027' });
    expect(work).toMatchObject({ platform: 'dlsite', kind: 'audio', playtimeMinutes: null });
    expect(work.achievements).toBeNull();
    expect(work.lastPlayedAt).toBeNull();
    expect(workMeta(work)).toBe('音声 · DLsite');
    expect(availabilityLabel({ kind: 'audio', installed: true })).toBe('已下载');
    expect(availabilityLabel({ kind: 'game', installed: false })).toBe('未安装');
  });
});
