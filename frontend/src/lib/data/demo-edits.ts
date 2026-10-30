import { noteMaxLength, ratingScale, type GameStatus } from './types';

/** Personal demo changes. Only ever stored for the synthetic demo dataset. */
export interface DemoGameEdits {
  status?: GameStatus;
  rating?: number | null;
  note?: string;
  favorite?: boolean;
}

export type DemoEdits = Readonly<Record<string, DemoGameEdits>>;

export interface DemoEditStore {
  read(): DemoEdits;
  write(edits: DemoEdits): void;
  clear(): void;
}

/** Bump when the stored shape changes; older payloads are ignored, not migrated. */
export const demoEditsVersion = 1;
export const demoDatasetId = 'atlas-demo-41544c41';
export const demoEditsKey = `library-atlas.demo-edits.v${demoEditsVersion}.${demoDatasetId}`;

const statuses = new Set<string>(['unplayed', 'playing', 'completed', 'paused']);
const demoId = /^demo-\d{5}$/;

export function isValidRating(value: unknown): value is number {
  return (
    typeof value === 'number' &&
    Number.isInteger(value) &&
    value >= ratingScale.min &&
    value <= ratingScale.max
  );
}

/** Drops anything malformed so a stale or edited payload cannot break the page. */
export function sanitizeDemoEdits(input: unknown): DemoEdits {
  if (!input || typeof input !== 'object') return {};
  const payload = input as { version?: unknown; dataset?: unknown; games?: unknown };
  if (payload.version !== demoEditsVersion || payload.dataset !== demoDatasetId) return {};
  if (!payload.games || typeof payload.games !== 'object') return {};
  const result: Record<string, DemoGameEdits> = {};
  for (const [id, raw] of Object.entries(payload.games as Record<string, unknown>)) {
    if (!demoId.test(id) || !raw || typeof raw !== 'object') continue;
    const entry = raw as Record<string, unknown>;
    const edits: DemoGameEdits = {};
    if (typeof entry.status === 'string' && statuses.has(entry.status))
      edits.status = entry.status as GameStatus;
    if (entry.rating === null || isValidRating(entry.rating)) edits.rating = entry.rating;
    if (typeof entry.note === 'string' && entry.note.length <= noteMaxLength)
      edits.note = entry.note;
    if (typeof entry.favorite === 'boolean') edits.favorite = entry.favorite;
    if (Object.keys(edits).length) result[id] = edits;
  }
  return result;
}

export function createMemoryEditStore(initial: DemoEdits = {}): DemoEditStore {
  let edits = initial;
  return {
    read: () => edits,
    write: (next) => {
      edits = next;
    },
    clear: () => {
      edits = {};
    },
  };
}

/** Browser storage keyed by demo version and dataset; parsed once, then cached. */
export function createBrowserEditStore(storage: Storage, key = demoEditsKey): DemoEditStore {
  let cache: DemoEdits | null = null;
  return {
    read() {
      if (cache) return cache;
      try {
        const raw = storage.getItem(key);
        cache = raw ? sanitizeDemoEdits(JSON.parse(raw)) : {};
      } catch {
        cache = {};
      }
      return cache;
    },
    write(next) {
      // Throws on quota or blocked storage; callers surface that as a failed save.
      storage.setItem(
        key,
        JSON.stringify({ version: demoEditsVersion, dataset: demoDatasetId, games: next }),
      );
      cache = next;
    },
    clear() {
      storage.removeItem(key);
      cache = {};
    },
  };
}

export function createDefaultEditStore(): DemoEditStore {
  try {
    if (typeof window !== 'undefined' && window.localStorage)
      return createBrowserEditStore(window.localStorage);
  } catch {
    // Storage can be blocked by browser policy; fall back to this page session.
  }
  return createMemoryEditStore();
}
