import { useSyncExternalStore } from 'react';
import { apiWrite } from './api-client';

/**
 * The one audio session in the app. It lives outside the page tree, so moving between pages does
 * not stop it, and there is only ever one element, so two things can never play at once. It never
 * starts by itself: not on load, not after a restart, only from a click.
 */
export interface SessionTrack {
  copyId: string;
  trackId: string;
  workId: string;
  name: string;
  /** Where to begin, if the user is continuing. */
  startAt?: number;
}

export type LoopMode = 'off' | 'all' | 'one';

export interface AudioState {
  queue: SessionTrack[];
  index: number;
  playing: boolean;
  position: number;
  duration: number | null;
  volume: number;
  muted: boolean;
  rate: number;
  loop: LoopMode;
  shuffle: boolean;
  sleepAt: number | null;
  sleepMinutes: number;
  error: string | null;
}

const SAVE_EVERY_MS = 5_000;

let state: AudioState = {
  queue: [],
  index: 0,
  playing: false,
  position: 0,
  duration: null,
  volume: 1,
  muted: false,
  rate: 1,
  loop: 'off',
  shuffle: false,
  sleepAt: null,
  sleepMinutes: 0,
  error: null,
};
const listeners = new Set<() => void>();
let element: HTMLAudioElement | null = null;
let lastSaved = 0;
/** Until a file's start is known its place is not: saving then would wipe the one on record. */
let settled = false;
let sleepTimer: number | null = null;
/** Bumped on every track change, so a late event from the old track changes nothing. */
let generation = 0;

function set(patch: Partial<AudioState>) {
  state = { ...state, ...patch };
  listeners.forEach((listener) => listener());
}

function current(): SessionTrack | undefined {
  return state.queue[state.index];
}

function saveProgress(force = false) {
  const track = current();
  if (!track || !element || !settled) return;
  const now = Date.now();
  if (!force && now - lastSaved < SAVE_EVERY_MS) return;
  lastSaved = now;
  const duration = Number.isFinite(element.duration) ? element.duration : null;
  void apiWrite('PUT', '/api/v1/media/audio-progress', {
    copyId: track.copyId,
    trackId: track.trackId,
    position: element.currentTime,
    duration,
  }).catch(() => undefined);
}

function nextIndex(step: number): number | null {
  const count = state.queue.length;
  if (!count) return null;
  if (state.shuffle && count > 1) {
    let pick = state.index;
    while (pick === state.index) pick = Math.floor(Math.random() * count);
    return pick;
  }
  const target = state.index + step;
  if (target >= 0 && target < count) return target;
  return state.loop === 'all' ? (target + count) % count : null;
}

function audio(): HTMLAudioElement {
  if (element) return element;
  const created = new Audio();
  created.preload = 'metadata';
  created.addEventListener('timeupdate', () => {
    set({ position: created.currentTime });
    saveProgress();
  });
  created.addEventListener('durationchange', () =>
    set({ duration: Number.isFinite(created.duration) ? created.duration : null }),
  );
  created.addEventListener('play', () => set({ playing: true }));
  created.addEventListener('pause', () => {
    set({ playing: false });
    saveProgress(true);
  });
  created.addEventListener('ended', () => {
    saveProgress(true);
    if (state.loop === 'one') {
      created.currentTime = 0;
      void created.play();
      return;
    }
    const next = nextIndex(1);
    if (next === null) set({ playing: false });
    else load(next, true);
  });
  // A file that cannot be read stops here: it is said once, and never retried in a loop.
  created.addEventListener('error', () => {
    set({ playing: false, error: '这个文件无法播放，可能格式不受支持或文件已移走。' });
  });
  element = created;
  return created;
}

function load(index: number, play: boolean) {
  const target = audio();
  saveProgress(true);
  const track = state.queue[index];
  if (!track) return;
  generation += 1;
  const mine = generation;
  settled = false;
  set({ index, position: track.startAt ?? 0, duration: null, error: null });
  target.src = `/api/v1/media/audio/${encodeURIComponent(track.copyId)}/${encodeURIComponent(track.trackId)}`;
  target.playbackRate = state.rate;
  target.addEventListener(
    'loadedmetadata',
    () => {
      if (mine !== generation) return;
      // A position beyond the end means the file is not the one it was saved for.
      if (track.startAt && track.startAt < target.duration) target.currentTime = track.startAt;
      settled = true;
    },
    { once: true },
  );
  if (play) void target.play().catch(() => undefined);
}

export const audioSession = {
  /** Always from a click. */
  playQueue(queue: SessionTrack[], index: number) {
    // Before the queue changes, while "the current track" still means the one being left.
    saveProgress(true);
    settled = false;
    set({ queue });
    load(index, true);
  },
  toggle() {
    const target = audio();
    if (target.paused) void target.play().catch(() => undefined);
    else target.pause();
  },
  next() {
    const target = nextIndex(1);
    if (target !== null) load(target, true);
  },
  previous() {
    // A little way in, "previous" means the start of this one, as on any player.
    if (element && element.currentTime > 3) element.currentTime = 0;
    else {
      const target = nextIndex(-1);
      if (target !== null) load(target, true);
    }
  },
  seek(position: number) {
    audio().currentTime = position;
    set({ position });
  },
  setVolume(volume: number) {
    audio().volume = volume;
    set({ volume, muted: volume === 0 ? state.muted : false });
    audio().muted = volume === 0 ? state.muted : false;
  },
  toggleMute() {
    const muted = !state.muted;
    audio().muted = muted;
    set({ muted });
  },
  setRate(rate: number) {
    audio().playbackRate = rate;
    set({ rate });
  },
  setLoop(loop: LoopMode) {
    set({ loop });
  },
  toggleShuffle() {
    set({ shuffle: !state.shuffle });
  },
  /** Minutes from now; 0 cancels. The stop is real: it pauses, and nothing starts it again. */
  sleep(minutes: number) {
    if (sleepTimer !== null) window.clearTimeout(sleepTimer);
    sleepTimer = null;
    if (minutes <= 0) {
      set({ sleepAt: null, sleepMinutes: 0 });
      return;
    }
    set({ sleepAt: Date.now() + minutes * 60_000, sleepMinutes: minutes });
    sleepTimer = window.setTimeout(() => {
      audio().pause();
      set({ sleepAt: null, sleepMinutes: 0 });
      sleepTimer = null;
    }, minutes * 60_000);
  },
  /** Ends the session. The mini player goes away with it. */
  close() {
    saveProgress(true);
    settled = false;
    if (element) {
      element.pause();
      element.removeAttribute('src');
      element.load();
    }
    set({ queue: [], index: 0, playing: false, position: 0, duration: null, error: null });
  },
};

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useAudioSession(): AudioState {
  return useSyncExternalStore(subscribe, () => state);
}

// Leaving the page keeps the latest place, if the browser lets the request through.
if (typeof window !== 'undefined') {
  window.addEventListener('pagehide', () => saveProgress(true));
}
