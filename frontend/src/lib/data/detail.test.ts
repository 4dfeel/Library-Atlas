import { describe, expect, it } from 'vitest';
import {
  createBrowserEditStore,
  createMemoryEditStore,
  demoDatasetId,
  demoEditsKey,
  demoEditsVersion,
} from './demo-edits';
import { DemoLibrarySource } from './demo-source';
import { generateDemoGames } from './generator';
import { defaultLibraryFilters, GameUnavailableError, type GameUpdate } from './types';

const filters = { ...defaultLibraryFilters };
const games = generateDemoGames(1500);
const nonOrdinary = ['private', 'hidden', 'quarantined'].map((visibility) =>
  games.find((game) => game.visibility === visibility)!,
);

function memorySource() {
  return new DemoLibrarySource(1500, { store: createMemoryEditStore() });
}

class FakeStorage implements Storage {
  private values = new Map<string, string>();
  get length() {
    return this.values.size;
  }
  clear() {
    this.values.clear();
  }
  getItem(key: string) {
    return this.values.get(key) ?? null;
  }
  key(index: number) {
    return [...this.values.keys()][index] ?? null;
  }
  removeItem(key: string) {
    this.values.delete(key);
  }
  setItem(key: string, value: string) {
    this.values.set(key, value);
  }
}

describe('detail reads by stable ID', () => {
  it('returns the same public record the Library lists, with detail fields', async () => {
    const source = memorySource();
    const listed = (await source.list({ filters })).items[0]!;
    const detail = await source.getGame({ id: listed.id });
    expect(detail).toMatchObject({
      id: 'demo-00001',
      title: listed.title,
      status: listed.status,
      favorite: listed.favorite,
      installed: listed.installed,
      playtimeMinutes: listed.playtimeMinutes,
    });
    expect(detail.description).toContain('天文台');
    expect(detail.tags.length).toBeGreaterThanOrEqual(3);
    expect(detail.achievements).not.toBeNull();
    expect(detail.rating).not.toBeNull();
    expect(detail.note).not.toBe('');
    expect(await memorySource().getGame({ id: listed.id })).toEqual(detail);
  });

  it('keeps unknown, absent and zero distinct in the fixed samples', async () => {
    const source = memorySource();
    expect((await source.getGame({ id: 'demo-00002' })).achievements).toBeNull();
    const unplayed = await source.getGame({ id: 'demo-00008' });
    expect(unplayed).toMatchObject({ status: 'unplayed', playtimeMinutes: 0, lastPlayedAt: null });
    expect(unplayed.achievements?.unlocked).toBe(0);
    expect(await source.getGame({ id: 'demo-00003' })).toMatchObject({ rating: null, note: '' });
    expect((await source.getGame({ id: 'demo-00010' })).background).toBeNull();
    expect(await source.getGame({ id: 'demo-00025' })).toMatchObject({
      background: null,
      cover: { kind: 'missing' },
    });
    expect((await source.getGame({ id: 'demo-00174' })).playtimeMinutes).toBeNull();
  });

  it('treats private, hidden, unconfirmed, absent and malformed IDs identically', async () => {
    const source = memorySource();
    const ids = [...nonOrdinary.map((game) => game.id), 'demo-99999', '../demo-00001', ''];
    for (const id of ids) {
      const error = await source.getGame({ id }).catch((caught: unknown) => caught);
      expect(error).toBeInstanceOf(GameUnavailableError);
      expect((error as Error).message).toBe('游戏暂不可用。');
      expect(JSON.stringify(error)).not.toContain('PRIVATE_SENTINEL');
    }
  });

  it('honours loading abort and error previews', async () => {
    const source = memorySource();
    await expect(source.getGame({ id: 'demo-00001', scenario: 'error' })).rejects.toThrow(
      '演示数据暂时无法读取',
    );
    const controller = new AbortController();
    const pending = source.getGame({
      id: 'demo-00001',
      scenario: 'loading',
      signal: controller.signal,
    });
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
  });
});

describe('detail writes', () => {
  it('cannot be used to read or modify non-ordinary or absent records', async () => {
    const store = createMemoryEditStore();
    const source = new DemoLibrarySource(1500, { store });
    for (const id of [...nonOrdinary.map((game) => game.id), 'demo-99999']) {
      await expect(source.updateGame(id, { note: 'probe' })).rejects.toBeInstanceOf(
        GameUnavailableError,
      );
      await expect(source.toggleFavorite(id)).rejects.toBeInstanceOf(GameUnavailableError);
    }
    expect(store.read()).toEqual({});
  });

  it('validates ratings, notes and rejects non-personal fields', async () => {
    const source = memorySource();
    for (const rating of [0, 6, 2.5, Number.NaN])
      await expect(source.updateGame('demo-00001', { rating })).rejects.toThrow('1–5');
    await expect(source.updateGame('demo-00001', { note: 'x'.repeat(1001) })).rejects.toThrow(
      '最多',
    );
    await expect(
      source.updateGame('demo-00001', { visibility: 'private' } as unknown as GameUpdate),
    ).rejects.toThrow('没有可保存的修改');
    await expect(
      source.updateGame('demo-00001', { status: 'deleted' } as unknown as GameUpdate),
    ).rejects.toThrow('状态无效');
  });

  it('sets and clears a rating and trims notes without touching other games', async () => {
    const source = memorySource();
    expect((await source.updateGame('demo-00003', { rating: 4 })).rating).toBe(4);
    expect((await source.updateGame('demo-00003', { rating: null })).rating).toBeNull();
    expect((await source.updateGame('demo-00003', { note: '  第一章结束  ' })).note).toBe(
      '第一章结束',
    );
    expect((await source.getGame({ id: 'demo-00004' })).note).not.toBe('第一章结束');
  });

  it('updates the Library status display and status filters', async () => {
    const source = memorySource();
    await source.updateGame('demo-00001', { status: 'paused' });
    const listed = (await source.list({ filters })).items.find((game) => game.id === 'demo-00001');
    expect(listed?.status).toBe('paused');
    const completed = await source.list({ filters: { ...filters, status: 'completed' } });
    expect(completed.items.some((game) => game.id === 'demo-00001')).toBe(false);
    const paused = await source.list({ filters: { ...filters, status: 'paused' } });
    expect(paused.items.some((game) => game.id === 'demo-00001')).toBe(true);
  });

  it('reports failed writes instead of pretending they succeeded', async () => {
    const store = createMemoryEditStore();
    const source = new DemoLibrarySource(1500, { store, failWrites: true });
    await expect(source.updateGame('demo-00001', { note: '不会保存' })).rejects.toThrow('尚未保存');
    expect(store.read()).toEqual({});
    const broken = new DemoLibrarySource(1500, {
      store: {
        ...createMemoryEditStore(),
        write: () => {
          throw new DOMException('quota', 'QuotaExceededError');
        },
      },
    });
    await expect(broken.updateGame('demo-00001', { rating: 2 })).rejects.toThrow('本机存储不可用');
  });
});

describe('versioned demo edit storage', () => {
  it('persists across source instances and resets explicitly', async () => {
    const storage = new FakeStorage();
    const first = new DemoLibrarySource(1500, { store: createBrowserEditStore(storage) });
    await first.updateGame('demo-00001', { rating: 2, note: '刷新后仍在', favorite: false });
    expect(JSON.parse(storage.getItem(demoEditsKey)!)).toMatchObject({
      version: demoEditsVersion,
      dataset: demoDatasetId,
    });
    const reloaded = new DemoLibrarySource(1500, { store: createBrowserEditStore(storage) });
    expect(await reloaded.getGame({ id: 'demo-00001' })).toMatchObject({
      rating: 2,
      note: '刷新后仍在',
      favorite: false,
    });
    expect(reloaded.editedCount()).toBe(1);
    await reloaded.resetEdits();
    expect(storage.getItem(demoEditsKey)).toBeNull();
    expect((await reloaded.getGame({ id: 'demo-00001' })).rating).toBe(
      (await memorySource().getGame({ id: 'demo-00001' })).rating,
    );
  });

  it('ignores other versions, other datasets, malformed values and corrupt JSON', async () => {
    const storage = new FakeStorage();
    const privateId = nonOrdinary[0]!.id;
    storage.setItem(
      demoEditsKey,
      JSON.stringify({
        version: demoEditsVersion,
        dataset: demoDatasetId,
        games: {
          'demo-00001': { rating: 9, note: 42, status: 'deleted', favorite: 'yes' },
          'demo-00003': { rating: 5 },
          [privateId]: { note: 'should never surface' },
          'not-a-demo-id': { rating: 3 },
        },
      }),
    );
    const source = new DemoLibrarySource(1500, { store: createBrowserEditStore(storage) });
    const baseline = await memorySource().getGame({ id: 'demo-00001' });
    expect(await source.getGame({ id: 'demo-00001' })).toEqual(baseline);
    expect((await source.getGame({ id: 'demo-00003' })).rating).toBe(5);
    await expect(source.getGame({ id: privateId })).rejects.toBeInstanceOf(GameUnavailableError);

    for (const payload of [
      JSON.stringify({
        version: 0,
        dataset: demoDatasetId,
        games: { 'demo-00003': { rating: 5 } },
      }),
      JSON.stringify({
        version: demoEditsVersion,
        dataset: 'other',
        games: { 'demo-00003': { rating: 5 } },
      }),
      '{not json',
    ]) {
      const other = new FakeStorage();
      other.setItem(demoEditsKey, payload);
      const isolated = new DemoLibrarySource(1500, { store: createBrowserEditStore(other) });
      expect((await isolated.getGame({ id: 'demo-00003' })).rating).toBeNull();
    }
  });
});
