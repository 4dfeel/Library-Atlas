import { generateDemoGames } from './generator';
import { isOrdinaryGame, selectLibrary } from './selectors';
import type { DemoSize, Game, LibraryRequest, LibraryResult, LibrarySource } from './types';

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

export class DemoLibrarySource implements LibrarySource {
  readonly mode = 'demo' as const;
  private readonly games: readonly Game[];
  private readonly favoriteOverrides = new Map<string, boolean>();

  constructor(size: DemoSize) {
    this.games = generateDemoGames(size);
  }

  async list({ filters, scenario = 'normal', signal }: LibraryRequest): Promise<LibraryResult> {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    if (scenario === 'loading') await waitForPreview(signal);
    if (scenario === 'error') throw new Error('演示数据暂时无法读取，请重试。');
    const ordinary = this.games
      .filter(isOrdinaryGame)
      .map((game) => ({ ...game, favorite: this.favoriteOverrides.get(game.id) ?? game.favorite }));
    return selectLibrary(scenario === 'empty' ? [] : ordinary, filters);
  }

  async toggleFavorite(id: string): Promise<void> {
    const game = this.games.find((entry) => entry.id === id && isOrdinaryGame(entry));
    if (!game) throw new Error('游戏暂不可用。');
    this.favoriteOverrides.set(id, !(this.favoriteOverrides.get(id) ?? game.favorite));
  }
}

const sources = new Map<DemoSize, DemoLibrarySource>();

export function getDemoSource(size: DemoSize): DemoLibrarySource {
  const existing = sources.get(size);
  if (existing) return existing;
  const source = new DemoLibrarySource(size);
  sources.set(size, source);
  return source;
}
