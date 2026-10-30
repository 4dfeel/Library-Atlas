import { createContext, useContext } from 'react';

/** Shell-level actions any page may trigger (panels and toasts live in the shell). */
export interface ShellActions {
  notify: (message: string, tone?: 'success' | 'error') => void;
  openSources: () => void;
  openTasks: () => void;
}

export const ShellContext = createContext<ShellActions | null>(null);

export function useShell(): ShellActions {
  const shell = useContext(ShellContext);
  if (!shell) throw new Error('useShell must be used inside the AppShell.');
  return shell;
}
