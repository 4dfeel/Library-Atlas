import { useSyncExternalStore } from 'react';

/**
 * Minimal History API routing for the two checkpoint routes. A router dependency
 * is not justified yet; swap this module if nested routes arrive in later phases.
 */
export type Route =
  | { name: 'dashboard' }
  | { name: 'library' }
  | { name: 'game'; id: string }
  | { name: 'settings' }
  | { name: 'downloads' }
  | { name: 'not-found' };

/** Entry state written by Atlas. Other keys in history.state are preserved. */
export interface AtlasHistoryState {
  /** This detail entry was pushed from a Library entry directly behind it. */
  fromLibrary?: boolean;
  /** This detail entry was pushed from the Dashboard entry directly behind it. */
  fromDashboard?: boolean;
  /** First visible item index of the Library entry, restored on return. */
  libraryAnchor?: number;
  /** Game whose link should regain focus when returning to this Library entry. */
  libraryFocusId?: string;
  /** Focus the Library search after arriving (Ctrl+K from another page). */
  focusSearch?: boolean;
}

// Bumped on every navigation (push, replace via navigate, popstate). Silent URL
// rewrites such as Library filter sync do not count as navigation.
let version = 0;
const listeners = new Set<() => void>();
const emit = () => {
  version++;
  listeners.forEach((listener) => listener());
};
if (typeof window !== 'undefined') window.addEventListener('popstate', emit);

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const snapshot = () => version;

/** Changes whenever history navigates; read the route from window.location. */
export function useLocationKey(): number {
  return useSyncExternalStore(subscribe, snapshot);
}

export function readHistoryState(): AtlasHistoryState {
  const state: unknown = window.history.state;
  if (!state || typeof state !== 'object' || !('atlas' in state)) return {};
  const atlas = (state as { atlas: unknown }).atlas;
  return atlas && typeof atlas === 'object' ? (atlas as AtlasHistoryState) : {};
}

/** Merges into the current entry without notifying subscribers or changing the URL. */
export function patchHistoryState(patch: AtlasHistoryState, url = window.location.href) {
  const base: unknown = window.history.state;
  const current = base && typeof base === 'object' ? base : {};
  window.history.replaceState({ ...current, atlas: { ...readHistoryState(), ...patch } }, '', url);
}

export function navigate(
  to: string,
  options: { replace?: boolean; state?: AtlasHistoryState } = {},
) {
  const entry = { atlas: options.state ?? {} };
  if (options.replace) window.history.replaceState(entry, '', to);
  else window.history.pushState(entry, '', to);
  emit();
}

export function matchRoute(pathname: string): Route {
  const path = pathname.replace(/\/+$/, '') || '/';
  if (path === '/') return { name: 'dashboard' };
  if (path === '/library') return { name: 'library' };
  if (path === '/settings') return { name: 'settings' };
  if (path === '/downloads') return { name: 'downloads' };
  const match = /^\/library\/([^/]+)$/.exec(path);
  if (match) {
    try {
      return { name: 'game', id: decodeURIComponent(match[1]!) };
    } catch {
      return { name: 'not-found' };
    }
  }
  return { name: 'not-found' };
}

export const settingsHref = '/settings';

export function gameHref(id: string, size: number): string {
  return `/library/${encodeURIComponent(id)}${size === 5000 ? '?size=5000' : ''}`;
}

export function downloadsHref(): string {
  return '/downloads';
}

export function libraryHref(size: number): string {
  return size === 5000 ? '/library?size=5000' : '/library';
}

export function dashboardHref(size: number, scope = 'all'): string {
  const params = new URLSearchParams();
  if (scope !== 'all') params.set('scope', scope);
  if (size === 5000) params.set('size', '5000');
  return `/${params.size ? `?${params}` : ''}`;
}
