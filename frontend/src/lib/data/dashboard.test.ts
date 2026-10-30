import { afterEach, describe, expect, it, vi } from 'vitest';
import { dashboardScopes, scopeLibraryFilters, selectDashboard } from './dashboard';
import { createConnectionStore, demoConnectionsKey } from './demo-connections';
import { createMemoryEditStore } from './demo-edits';
import { DemoLibrarySource } from './demo-source';
import { createTaskService, failsFirstAttempt, type DemoTask } from './demo-tasks';
import { generateDemoGames } from './generator';
import { selectLibrary } from './selectors';
import { defaultLibraryFilters, type Game } from './types';

const games = generateDemoGames(1500);
const ordinary = games.filter((game) => game.visibility === 'normal');
const filters = { ...defaultLibraryFilters };

describe('identity and capabilities', () => {
  it('keys works by (platform, sourceId); equal source numbers across platforms do not collide', () => {
    const keys = new Set(games.map((game) => `${game.platform}:${game.sourceId}`));
    expect(keys.size).toBe(games.length);
    const shared = games.find(
      (game) =>
        game.platform === 'dlsite' &&
        games.some((other) => other.platform === 'steam' && other.sourceId === game.sourceId),
    );
    expect(shared).toBeDefined();
  });

  it('never gives Steam or viewer-only works a download, and keeps unknown sizes null', () => {
    expect(
      games
        .filter((game) => game.platform === 'steam')
        .every((game) => !game.capabilities.download),
    ).toBe(true);
    const viewerOnly = games.filter((game) => game.capabilities.officialViewerOnly);
    expect(viewerOnly.length).toBeGreaterThan(0);
    expect(
      viewerOnly.every((game) => !game.capabilities.download && !game.capabilities.extract),
    ).toBe(true);
    expect(games.some((game) => game.file && game.file.sizeBytes === null)).toBe(true);
    expect(games.every((game) => game.file === null || game.file.sizeBytes !== 0)).toBe(true);
  });
});

describe('dashboard aggregation', () => {
  it('applies privacy before every count, pick and chart', () => {
    for (const scope of dashboardScopes) {
      const result = selectDashboard(games, scope);
      expect(JSON.stringify(result)).not.toContain('PRIVATE_SENTINEL');
      expect(result.sources.steam.works + result.sources.dlsite.works).toBe(ordinary.length);
    }
    const privateOnly: Game[] = games
      .filter((game) => game.visibility !== 'normal')
      .map((game) => ({ ...game, favorite: true, installed: true }));
    const leaked = selectDashboard(privateOnly, 'all');
    expect(leaked.totals.works).toBe(0);
    expect(leaked.recent).toEqual([]);
    expect(leaked.featured).toEqual([]);
    expect(leaked.recommendations).toEqual([]);
  });

  it('matches the Library count for every scope through its Library filters', () => {
    for (const scope of dashboardScopes) {
      const result = selectDashboard(games, scope);
      const listed = selectLibrary(games, { ...filters, ...scopeLibraryFilters(scope) });
      expect(listed.filteredCount).toBe(result.totals.works);
    }
  });

  it('counts game statistics over games only and keeps unknown separate from zero', () => {
    const result = selectDashboard(games, 'all');
    const gameRows = ordinary.filter((game) => game.kind === 'game');
    expect(result.totals.games).toBe(gameRows.length);
    expect(result.totals.playedGames).toBe(
      gameRows.filter((game) => (game.playtimeMinutes ?? 0) > 0).length,
    );
    expect(result.totals.unknownPlaytimeGames).toBe(
      gameRows.filter((game) => game.playtimeMinutes === null).length,
    );
    expect(result.totals.unstartedGames).toBe(
      gameRows.filter((game) => game.status === 'unplayed').length,
    );
    expect(result.totals.playtimeMinutes).toBe(
      gameRows.reduce((sum, game) => sum + (game.playtimeMinutes ?? 0), 0),
    );
    // Buckets cover exactly the games with play time above zero.
    expect(result.playtimeBuckets.reduce((sum, bucket) => sum + bucket.count, 0)).toBe(
      result.totals.playedGames,
    );
    // Genres are single-valued: one count per game, mutually exclusive.
    expect(result.genres.reduce((sum, entry) => sum + entry.count, 0)).toBe(result.totals.games);
    expect(result.mostPlayed.every((game) => game.kind === 'game')).toBe(true);
    // DLsite games report no play time: the scope shows unknowns, not zero hours.
    const dlsiteGames = selectDashboard(games, 'dlsite-games');
    expect(dlsiteGames.totals.playedGames).toBe(0);
    expect(dlsiteGames.totals.unknownPlaytimeGames).toBe(dlsiteGames.totals.games);
  });

  it('uses non-game semantics for the DLsite media range', () => {
    const media = selectDashboard(games, 'dlsite-media');
    expect(media.hasGames).toBe(false);
    expect(media.totals.games).toBe(0);
    expect(media.recommendations.every(({ game }) => game.kind !== 'game')).toBe(true);
    expect(media.recent.every((game) => game.lastPlayedAt !== null)).toBe(true);
  });

  it('is reproducible per batch and changes only when asked', () => {
    const first = selectDashboard(games, 'all', 0).recommendations.map(({ game }) => game.id);
    expect(selectDashboard(games, 'all', 0).recommendations.map(({ game }) => game.id)).toEqual(
      first,
    );
    expect(selectDashboard(games, 'all', 1).recommendations.map(({ game }) => game.id)).not.toEqual(
      first,
    );
    for (const { game } of selectDashboard(games, 'games', 3).recommendations)
      expect(['unplayed', 'paused']).toContain(game.status);
  });

  it('reflects demo edits: status, favorite and download state', async () => {
    const source = new DemoLibrarySource(1500, { store: createMemoryEditStore() });
    const before = await source.dashboard({ scope: 'all' });
    await source.updateGame('demo-00001', { status: 'unplayed', favorite: false });
    source.markDownloaded('demo-00033');
    const after = await source.dashboard({ scope: 'all' });
    expect(after.backlog.unplayed).toBe(before.backlog.unplayed + 1);
    expect(after.totals.favorites).toBe(before.totals.favorites - 1);
    expect(after.totals.local).toBe(before.totals.local + 1);
    expect((await source.getGame({ id: 'demo-00033' })).installed).toBe(true);
    expect(() => source.markDownloaded('demo-00001')).toThrow('不支持');
    expect(() => source.markDownloaded('demo-00098')).toThrow('暂不可用');
  });
});

describe('demo connections', () => {
  afterEach(() => vi.useRealTimers());

  it('connects, expires, fails once, retries and disconnects without touching works', () => {
    vi.useFakeTimers();
    const storage = window.localStorage;
    storage.removeItem(demoConnectionsKey);
    const store = createConnectionStore({ storage, connectDelayMs: 100 });
    expect(store.getSnapshot().dlsite.state).toBe('connected');
    store.expire('dlsite');
    expect(store.getSnapshot().dlsite.state).toBe('expired');
    store.failNextConnect('dlsite');
    store.connect('dlsite');
    expect(store.getSnapshot().dlsite.state).toBe('connecting');
    vi.advanceTimersByTime(100);
    expect(store.getSnapshot().dlsite.state).toBe('error');
    store.connect('dlsite');
    vi.advanceTimersByTime(100);
    expect(store.getSnapshot().dlsite).toMatchObject({ state: 'connected', failNext: false });
    store.disconnect('steam');
    expect(store.getSnapshot().steam).toMatchObject({ state: 'disconnected', alias: null });
    // Coarse state persists; a reload restores it.
    expect(createConnectionStore({ storage }).getSnapshot().steam.state).toBe('disconnected');
    expect(JSON.stringify(store.getSnapshot())).not.toMatch(/@|password|token|cookie/i);
    store.reset();
  });

  it('cancels a pending demo connect on disconnect', () => {
    vi.useFakeTimers();
    const store = createConnectionStore({ connectDelayMs: 100 });
    store.disconnect('steam');
    store.connect('steam');
    store.disconnect('steam');
    vi.advanceTimersByTime(500);
    expect(store.getSnapshot().steam.state).toBe('disconnected');
  });
});

describe('demo download tasks', () => {
  afterEach(() => vi.useRealTimers());
  const work = (id: string, extract = true, sizeBytes: number | null = 10_000_000) => ({
    id,
    title: `作品 ${id}`,
    platform: 'dlsite' as const,
    capabilities: { download: true, extract, officialViewerOnly: false },
    file: { version: 'v1.0', sizeBytes },
  });

  it('walks queued → downloading → verifying → extracting → done and reports completion once', () => {
    vi.useFakeTimers();
    const completed: DemoTask[] = [];
    const service = createTaskService({ tickMs: 10, onComplete: (task) => completed.push(task) });
    const seen = new Set<string>();
    service.subscribe(() => seen.add(service.getSnapshot()[0]!.phase));
    service.start(work('demo-00033'));
    vi.advanceTimersByTime(10 * 40);
    expect([...seen]).toEqual(['queued', 'downloading', 'verifying', 'extracting', 'done']);
    expect(completed.map((task) => task.workId)).toEqual(['demo-00033']);
    vi.advanceTimersByTime(1000);
    expect(completed).toHaveLength(1);
  });

  it('skips extraction for single files and uses indeterminate progress for unknown size', () => {
    vi.useFakeTimers();
    const service = createTaskService({ tickMs: 10 });
    const phases: string[] = [];
    service.subscribe(() => {
      const task = service.getSnapshot()[0]!;
      phases.push(task.phase);
      if (task.phase === 'downloading') expect(task.progress).toBeNull();
    });
    service.start(work('demo-00027', false, null));
    vi.advanceTimersByTime(10 * 40);
    expect(phases).not.toContain('extracting');
    expect(phases.at(-1)).toBe('done');
  });

  it('reuses one task per work, cancels for good and retries failures', () => {
    vi.useFakeTimers();
    const completed: string[] = [];
    const service = createTaskService({
      tickMs: 10,
      onComplete: (task) => completed.push(task.workId),
    });
    expect(failsFirstAttempt('demo-00144')).toBe(true);
    service.start(work('demo-00144'));
    service.start(work('demo-00144'));
    expect(service.getSnapshot()).toHaveLength(1);
    vi.advanceTimersByTime(10 * 40);
    expect(service.getSnapshot()[0]).toMatchObject({ phase: 'failed', attempt: 1 });
    expect(service.getSnapshot()[0]!.error).toContain('校验失败');
    service.retry('demo-00144');
    vi.advanceTimersByTime(10 * 40);
    expect(service.getSnapshot()[0]).toMatchObject({ phase: 'done', attempt: 2 });

    service.start(work('demo-00033'));
    vi.advanceTimersByTime(30);
    service.cancel('demo-00033');
    vi.advanceTimersByTime(10_000);
    expect(service.getSnapshot().find((task) => task.workId === 'demo-00033')?.phase).toBe(
      'cancelled',
    );
    expect(completed).toEqual(['demo-00144']);
    service.clearFinished();
    expect(service.getSnapshot()).toEqual([]);
  });

  it('runs queued tasks one at a time and refuses works without download capability', () => {
    vi.useFakeTimers();
    const service = createTaskService({ tickMs: 10 });
    service.start(work('demo-00033'));
    service.start(work('demo-00051'));
    vi.advanceTimersByTime(30);
    const [first, second] = service.getSnapshot();
    expect(first!.phase).toBe('downloading');
    expect(second!.phase).toBe('queued');
    expect(() =>
      service.start({
        ...work('demo-00048'),
        capabilities: { download: false, extract: false, officialViewerOnly: true },
      }),
    ).toThrow('不支持');
    service.dispose();
  });
});
