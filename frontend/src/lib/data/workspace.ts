import { useSyncExternalStore } from 'react';

/**
 * Which library the app shows. Demo is synthetic and browser-only; real goes through the
 * local service. Only this choice is stored here, never anything from either library.
 */
export type WorkspaceMode = 'demo' | 'real';

export const demoAvailable = import.meta.env.VITE_DEMO_MODE !== 'false';
export const workspaceModeKey = 'library-atlas.workspace-mode.v1';

function readStored(): WorkspaceMode | null {
  try {
    const value = window.localStorage.getItem(workspaceModeKey);
    return value === 'demo' || value === 'real' ? value : null;
  } catch {
    return null;
  }
}

let current: WorkspaceMode =
  !demoAvailable || (typeof window !== 'undefined' && readStored() === 'real') ? 'real' : 'demo';
const listeners = new Set<() => void>();

export function getWorkspaceMode(): WorkspaceMode {
  return current;
}

export function setWorkspaceMode(mode: WorkspaceMode) {
  if (mode === current || (mode === 'demo' && !demoAvailable)) return;
  current = mode;
  try {
    window.localStorage.setItem(workspaceModeKey, mode);
  } catch {
    // Blocked storage only means the choice lasts for this page session.
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useWorkspaceMode(): WorkspaceMode {
  return useSyncExternalStore(subscribe, getWorkspaceMode);
}
