import type { Platform } from './types';

/**
 * Demo-only source connection states. Nothing here accepts or stores a password,
 * cookie or token: "演示连接" just moves the state machine. Real platform sign-in is
 * Phase 2 work behind the backend and the Windows credential store.
 */
export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'expired' | 'error';

export interface SourceConnection {
  platform: Platform;
  state: ConnectionState;
  /** Fictional alias; never a real account name or e-mail. */
  alias: string | null;
  /** Fixed demo timestamp; not the wall clock, so screenshots stay stable. */
  lastSyncAt: string | null;
  /** The next demo connect attempt fails once (for the retry flow). */
  failNext: boolean;
}

export type Connections = Readonly<Record<Platform, SourceConnection>>;

export const demoConnectionsKey = 'library-atlas.demo-sources.v1.atlas-demo-41544c41';
const demoSyncAt = '2026-10-30T11:15:00.000Z';
const aliases: Record<Platform, string> = {
  steam: 'Atlas 演示账号 · Steam',
  dlsite: 'Atlas 演示账号 · DLsite',
};

const connected = (platform: Platform): SourceConnection => ({
  platform,
  state: 'connected',
  alias: aliases[platform],
  lastSyncAt: demoSyncAt,
  failNext: false,
});

function initial(): Record<Platform, SourceConnection> {
  return { steam: connected('steam'), dlsite: connected('dlsite') };
}

export interface ConnectionStoreOptions {
  storage?: Storage | null;
  /** Simulated sign-in duration. */
  connectDelayMs?: number;
  /** Start with this source expired (`?state=source-expired`). */
  expired?: Platform | null;
}

/** Small external store: subscribe/getSnapshot for useSyncExternalStore. */
export function createConnectionStore({
  storage = null,
  connectDelayMs = 900,
  expired = null,
}: ConnectionStoreOptions = {}) {
  let state = initial();
  try {
    const raw = storage?.getItem(demoConnectionsKey);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    if (parsed && typeof parsed === 'object') {
      for (const platform of ['steam', 'dlsite'] as const) {
        const saved = (parsed as Record<string, unknown>)[platform];
        if (saved === 'disconnected' || saved === 'expired' || saved === 'error')
          state[platform] = {
            ...state[platform],
            state: saved,
            alias: saved === 'disconnected' ? null : state[platform].alias,
          };
      }
    }
  } catch {
    state = initial();
  }
  if (expired) state[expired] = { ...state[expired], state: 'expired' };

  const listeners = new Set<() => void>();
  const timers = new Map<Platform, ReturnType<typeof setTimeout>>();
  const set = (platform: Platform, patch: Partial<SourceConnection>) => {
    state = { ...state, [platform]: { ...state[platform], ...patch } };
    try {
      // Only coarse states persist; an in-flight "connecting" is never restored.
      storage?.setItem(
        demoConnectionsKey,
        JSON.stringify({
          steam: state.steam.state === 'connecting' ? 'disconnected' : state.steam.state,
          dlsite: state.dlsite.state === 'connecting' ? 'disconnected' : state.dlsite.state,
        }),
      );
    } catch {
      // Blocked storage only loses the demo preference.
    }
    listeners.forEach((listener) => listener());
  };

  return {
    getSnapshot: (): Connections => state,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    connect(platform: Platform) {
      if (state[platform].state === 'connecting') return;
      set(platform, { state: 'connecting' });
      timers.set(
        platform,
        setTimeout(() => {
          timers.delete(platform);
          if (state[platform].failNext) set(platform, { state: 'error', failNext: false });
          else set(platform, { ...connected(platform) });
        }, connectDelayMs),
      );
    },
    /** Next connect fails once, so the error and retry states can be reviewed. */
    failNextConnect(platform: Platform) {
      set(platform, { failNext: true });
    },
    expire(platform: Platform) {
      if (state[platform].state === 'connected') set(platform, { state: 'expired' });
    },
    /** Keeps imported works; only the (demo) session is dropped. */
    disconnect(platform: Platform) {
      clearTimeout(timers.get(platform));
      timers.delete(platform);
      set(platform, { state: 'disconnected', alias: null, failNext: false });
    },
    reset() {
      timers.forEach((timer) => clearTimeout(timer));
      timers.clear();
      state = initial();
      try {
        storage?.removeItem(demoConnectionsKey);
      } catch {
        // Ignore blocked storage.
      }
      listeners.forEach((listener) => listener());
    },
  };
}

export type ConnectionStore = ReturnType<typeof createConnectionStore>;
