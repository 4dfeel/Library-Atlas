import { createDefaultEditStore, isValidRating, type DemoEditStore } from './demo-edits';
import { selectDashboard, type DashboardResult, type DashboardScope } from './dashboard';
import { describeDemoGame } from './details';
import { generateDemoGames } from './generator';
import { isOrdinaryGame, selectLibrary } from './selectors';
import {
  GameUnavailableError,
  GameUpdateError,
  noteMaxLength,
  type DemoScenario,
  type DemoSize,
  type Game,
  type GameDetail,
  type GameRequest,
  type GameUpdate,
  type LibraryRequest,
  type LibraryResult,
  type LibrarySource,
} from './types';

const statuses = new Set<string>(['unplayed', 'playing', 'completed', 'paused']);

function waitForPreview(signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Aborted', 'AbortError'));
      return;
    }
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException('Aborted', 'AbortError'));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, 60_000);
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

async function previewScenario(scenario: DemoScenario, signal?: AbortSignal) {
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  if (scenario === 'loading') await waitForPreview(signal);
  if (scenario === 'error') throw new Error('演示数据暂时无法读取，请重试。');
}

function validateUpdate(update: GameUpdate): GameUpdate {
  const clean: GameUpdate = {};
  if ('status' in update) {
    if (typeof update.status !== 'string' || !statuses.has(update.status))
      throw new GameUpdateError('进度状态无效。');
    clean.status = update.status;
  }
  if ('rating' in update) {
    if (update.rating !== null && !isValidRating(update.rating))
      throw new GameUpdateError('评分须为 1–5 的整数星级。');
    clean.rating = update.rating ?? null;
  }
  if ('note' in update) {
    if (typeof update.note !== 'string') throw new GameUpdateError('备注格式无效。');
    const note = update.note.trim();
    if (note.length > noteMaxLength)
      throw new GameUpdateError(`备注最多 ${noteMaxLength.toLocaleString('zh-CN')} 字。`);
    clean.note = note;
  }
  if ('favorite' in update) {
    if (typeof update.favorite !== 'boolean') throw new GameUpdateError('收藏状态无效。');
    clean.favorite = update.favorite;
  }
  if (!Object.keys(clean).length) throw new GameUpdateError('没有可保存的修改。');
  return clean;
}

export interface DemoSourceOptions {
  store?: DemoEditStore;
  /** Makes every write fail, so the save-error state can be reviewed and tested. */
  failWrites?: boolean;
  /** Simulated local write latency, long enough to show a saving state. */
  writeDelayMs?: number;
}

export class DemoLibrarySource implements LibrarySource {
  readonly mode = 'demo' as const;
  private readonly games: readonly Game[];
  private readonly byId: ReadonlyMap<string, { game: Game; index: number }>;
  private readonly store: DemoEditStore;
  failWrites: boolean;
  private readonly writeDelayMs: number;

  constructor(size: DemoSize, options: DemoSourceOptions = {}) {
    this.games = generateDemoGames(size);
    this.byId = new Map(this.games.map((game, index) => [game.id, { game, index }]));
    this.store = options.store ?? createDefaultEditStore();
    this.failWrites = options.failWrites ?? false;
    this.writeDelayMs = options.writeDelayMs ?? 0;
  }

  /** Every by-ID read and write passes here; non-ordinary records look absent. */
  private ordinary(id: string): { game: Game; index: number } {
    const entry = typeof id === 'string' ? this.byId.get(id) : undefined;
    if (!entry || !isOrdinaryGame(entry.game)) throw new GameUnavailableError();
    return entry;
  }

  private withEdits(game: Game): Game {
    const edits = this.store.read()[game.id];
    if (!edits) return game;
    return {
      ...game,
      status: edits.status ?? game.status,
      favorite: edits.favorite ?? game.favorite,
      installed: game.installed || edits.downloaded === true,
    };
  }

  private detail(id: string): GameDetail {
    const { game, index } = this.ordinary(id);
    const fields = describeDemoGame(game, index);
    const edits = this.store.read()[id];
    return {
      ...this.withEdits(game),
      ...fields,
      rating: edits && 'rating' in edits ? (edits.rating ?? null) : fields.rating,
      note: edits?.note ?? fields.note,
    };
  }

  async list({ filters, scenario = 'normal', signal }: LibraryRequest): Promise<LibraryResult> {
    await previewScenario(scenario, signal);
    const ordinary = this.games.filter(isOrdinaryGame).map((game) => this.withEdits(game));
    return selectLibrary(scenario === 'empty' ? [] : ordinary, filters);
  }

  /** Same privacy-first snapshot as the Library: filter, then apply demo edits. */
  async dashboard({
    scope,
    batch = 0,
    scenario = 'normal',
    signal,
  }: {
    scope: DashboardScope;
    batch?: number;
    scenario?: DemoScenario;
    signal?: AbortSignal;
  }): Promise<DashboardResult> {
    await previewScenario(scenario === 'empty' ? 'normal' : scenario, signal);
    const ordinary = this.games.filter(isOrdinaryGame).map((game) => this.withEdits(game));
    return selectDashboard(scenario === 'empty' ? [] : ordinary, scope, batch);
  }

  async getGame({ id, scenario = 'normal', signal }: GameRequest): Promise<GameDetail> {
    await previewScenario(scenario === 'empty' ? 'normal' : scenario, signal);
    return this.detail(id);
  }

  async updateGame(id: string, update: GameUpdate): Promise<GameDetail> {
    this.ordinary(id);
    const clean = validateUpdate(update);
    if (this.writeDelayMs) await new Promise((resolve) => setTimeout(resolve, this.writeDelayMs));
    if (this.failWrites) throw new GameUpdateError('演示存储暂时无法写入，修改尚未保存。');
    const current = this.store.read();
    try {
      this.store.write({ ...current, [id]: { ...current[id], ...clean } });
    } catch {
      throw new GameUpdateError('本机存储不可用，修改尚未保存。');
    }
    return this.detail(id);
  }

  async toggleFavorite(id: string): Promise<void> {
    const { game } = this.ordinary(id);
    await this.updateGame(id, { favorite: !this.withEdits(game).favorite });
  }

  /**
   * Records a finished demo download. Only works whose capabilities allow it; this
   * never marks a game installed or launchable, only that demo files are present.
   */
  markDownloaded(id: string): void {
    const { game } = this.ordinary(id);
    if (!game.capabilities.download) throw new GameUpdateError('该作品不支持演示下载。');
    const current = this.store.read();
    this.store.write({ ...current, [id]: { ...current[id], downloaded: true } });
  }

  /** Number of locally stored demo records; used to describe the reset scope. */
  editedCount(): number {
    return Object.keys(this.store.read()).length;
  }

  async resetEdits(): Promise<void> {
    try {
      this.store.clear();
    } catch {
      throw new GameUpdateError('本机存储不可用，未能重置演示修改。');
    }
  }
}

const sharedStore = createDefaultEditStore();
const sources = new Map<DemoSize, DemoLibrarySource>();
const failWrites =
  typeof window !== 'undefined' &&
  new URLSearchParams(window.location.search).get('state') === 'save-error';

/** Both scale settings share one edit store: their first 1500 records are identical. */
export function getDemoSource(size: DemoSize): DemoLibrarySource {
  const existing = sources.get(size);
  if (existing) return existing;
  const source = new DemoLibrarySource(size, { store: sharedStore, failWrites, writeDelayMs: 160 });
  sources.set(size, source);
  return source;
}
