import type { Game, Platform } from './types';

/**
 * Demo download-and-extract tasks. Nothing is downloaded or written: one service
 * owns every task and a single timer advances them, so cards and pages never run
 * their own intervals. Tasks live in memory; a reload drops unfinished ones and
 * the work simply shows as not downloaded again. Finished results persist through
 * the demo edit store (`downloaded`).
 */
export type TaskPhase =
  'queued' | 'downloading' | 'verifying' | 'extracting' | 'done' | 'failed' | 'cancelled';

export interface DemoTask {
  /** One task per work: starting again reuses it. */
  workId: string;
  title: string;
  platform: Platform;
  sizeBytes: number | null;
  needsExtract: boolean;
  phase: TaskPhase;
  /** 0–1 for the current determinate phase; `null` while indeterminate. */
  progress: number | null;
  error: string | null;
  attempt: number;
}

const active = new Set<TaskPhase>(['queued', 'downloading', 'verifying', 'extracting']);
export const isActiveTask = (task: DemoTask) => active.has(task.phase);

/** Ticks per phase at the default 250ms tick: ~3s download, ~1s verify, ~2s extract. */
const downloadTicks = 12;
const verifyTicks = 4;
const extractTicks = 8;

/** Fixed demo failure: these works fail verification on their first attempt only. */
export function failsFirstAttempt(workId: string): boolean {
  return Number(workId.replace(/\D/g, '')) % 7 === 4;
}

export interface TaskServiceOptions {
  tickMs?: number;
  onComplete?: (task: DemoTask) => void;
}

export function createTaskService({ tickMs = 250, onComplete }: TaskServiceOptions = {}) {
  let tasks: DemoTask[] = [];
  const ticks = new Map<string, number>();
  const listeners = new Set<() => void>();
  let timer: ReturnType<typeof setInterval> | null = null;

  const emit = () => listeners.forEach((listener) => listener());
  const update = (workId: string, patch: Partial<DemoTask>) => {
    tasks = tasks.map((task) => (task.workId === workId ? { ...task, ...patch } : task));
  };
  const stopIfIdle = () => {
    if (timer && !tasks.some(isActiveTask)) {
      clearInterval(timer);
      timer = null;
    }
  };

  /** Advances the single running task one step; queued tasks wait their turn. */
  const tick = () => {
    const running =
      tasks.find((task) => task.phase !== 'queued' && isActiveTask(task)) ??
      tasks.find((task) => task.phase === 'queued');
    if (!running) return stopIfIdle();
    const count = (ticks.get(running.workId) ?? 0) + 1;
    ticks.set(running.workId, count);
    switch (running.phase) {
      case 'queued':
        ticks.set(running.workId, 0);
        update(running.workId, { phase: 'downloading', progress: running.sizeBytes ? 0 : null });
        break;
      case 'downloading':
        if (count >= downloadTicks) {
          ticks.set(running.workId, 0);
          update(running.workId, { phase: 'verifying', progress: null });
        } else if (running.sizeBytes) update(running.workId, { progress: count / downloadTicks });
        break;
      case 'verifying':
        if (count < verifyTicks) break;
        ticks.set(running.workId, 0);
        if (running.attempt === 1 && failsFirstAttempt(running.workId)) {
          update(running.workId, {
            phase: 'failed',
            progress: null,
            error: '校验失败：演示文件校验值不匹配。可以重试。',
          });
        } else if (running.needsExtract)
          update(running.workId, { phase: 'extracting', progress: 0 });
        else finish(running.workId);
        break;
      case 'extracting':
        if (count >= extractTicks) finish(running.workId);
        else update(running.workId, { progress: count / extractTicks });
        break;
      default:
        break;
    }
    emit();
    stopIfIdle();
  };

  const finish = (workId: string) => {
    update(workId, { phase: 'done', progress: 1, error: null });
    const task = tasks.find((entry) => entry.workId === workId);
    if (task) onComplete?.(task);
  };

  const ensureTimer = () => {
    if (!timer) timer = setInterval(tick, tickMs);
  };

  return {
    getSnapshot: (): readonly DemoTask[] => tasks,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    /** Starts or resumes the work's task. Active tasks are returned as-is. */
    start(work: Pick<Game, 'id' | 'title' | 'platform' | 'capabilities' | 'file'>): DemoTask {
      if (!work.capabilities.download) throw new Error('该作品不支持演示下载。');
      const existing = tasks.find((task) => task.workId === work.id);
      if (existing && isActiveTask(existing)) return existing;
      const next: DemoTask = {
        workId: work.id,
        title: work.title,
        platform: work.platform,
        sizeBytes: work.file?.sizeBytes ?? null,
        needsExtract: work.capabilities.extract,
        phase: 'queued',
        progress: null,
        error: null,
        attempt: (existing?.attempt ?? 0) + 1,
      };
      ticks.delete(work.id);
      tasks = existing
        ? tasks.map((task) => (task.workId === work.id ? next : task))
        : [...tasks, next];
      ensureTimer();
      emit();
      return next;
    },
    /** Restarts a failed or cancelled task with the details it was created with. */
    retry(workId: string) {
      const task = tasks.find((entry) => entry.workId === workId);
      if (!task || isActiveTask(task) || task.phase === 'done') return;
      this.start({
        id: task.workId,
        title: task.title,
        platform: task.platform,
        capabilities: { download: true, extract: task.needsExtract, officialViewerOnly: false },
        file: { version: '', sizeBytes: task.sizeBytes },
      });
    },
    /** A cancelled task stops for good; it never completes on its own later. */
    cancel(workId: string) {
      const task = tasks.find((entry) => entry.workId === workId);
      if (!task || !isActiveTask(task)) return;
      update(workId, { phase: 'cancelled', progress: null });
      ticks.delete(workId);
      emit();
      stopIfIdle();
    },
    clearFinished() {
      tasks = tasks.filter(isActiveTask);
      emit();
    },
    dispose() {
      if (timer) clearInterval(timer);
      timer = null;
      tasks = [];
      ticks.clear();
      emit();
    },
  };
}

export type TaskService = ReturnType<typeof createTaskService>;
