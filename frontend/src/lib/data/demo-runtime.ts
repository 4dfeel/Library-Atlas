import { createConnectionStore } from './demo-connections';
import { getDemoSource } from './demo-source';
import { createTaskService, type DemoTask } from './demo-tasks';
import type { DemoSize, Game } from './types';

/**
 * Page-lifetime demo services. One connection store and one task service exist for
 * the whole app, so every component sees the same state and only one timer runs.
 */
function browserStorage(): Storage | null {
  try {
    return typeof window !== 'undefined' ? window.localStorage : null;
  } catch {
    return null;
  }
}

const previewState =
  typeof window !== 'undefined' ? new URLSearchParams(window.location.search).get('state') : null;

export const demoConnections = createConnectionStore({
  storage: browserStorage(),
  expired: previewState === 'source-expired' ? 'dlsite' : null,
});

const taskSizes = new Map<string, DemoSize>();
const completionListeners = new Set<(task: DemoTask) => void>();

export const demoTasks = createTaskService({
  onComplete(task) {
    try {
      getDemoSource(taskSizes.get(task.workId) ?? 1500).markDownloaded(task.workId);
    } catch {
      // The work became unavailable mid-task; nothing to record.
    }
    completionListeners.forEach((listener) => listener(task));
  },
});

export function startDemoDownload(
  work: Pick<Game, 'id' | 'title' | 'platform' | 'capabilities' | 'file'>,
  size: DemoSize,
) {
  taskSizes.set(work.id, size);
  return demoTasks.start(work);
}

/** Lets the query layer refresh Library, detail and Dashboard after a finished task. */
export function onDemoTaskComplete(listener: (task: DemoTask) => void) {
  completionListeners.add(listener);
  return () => {
    completionListeners.delete(listener);
  };
}
