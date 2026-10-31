import type { ConnectionState, DemoTask, SourceStatus, TaskPhase } from '@/lib/data';

export const connectionLabels: Record<ConnectionState, string> = {
  connected: '已连接',
  connecting: '连接中',
  unverified: '暂时无法验证',
  expired: '会话已过期',
  error: '连接失败',
  disconnected: '未连接',
};

/** Real connection states map onto the shared badge; absent data is never "connected". */
export function realConnectionState(
  source: Pick<SourceStatus, 'connection'> | undefined,
): ConnectionState {
  switch (source?.connection) {
    case 'connected':
      return 'connected';
    case 'unverified':
      return 'unverified';
    case 'authenticating':
    case 'needs_verification':
    case 'verifying':
      return 'connecting';
    case 'reauth_required':
      return 'expired';
    case 'error':
    case 'disconnect_failed':
      return 'error';
    default:
      return 'disconnected';
  }
}

export const phaseLabels: Record<TaskPhase, string> = {
  queued: '排队中',
  downloading: '下载中',
  verifying: '校验中',
  extracting: '解压中',
  done: '已完成',
  failed: '失败',
  cancelled: '已取消',
};

/** Step names in the progress trail; nouns, so a cancelled task does not read as running. */
export const stepLabels: Partial<Record<TaskPhase, string>> = {
  downloading: '下载',
  verifying: '校验',
  extracting: '解压',
};

export function taskSummary(task: DemoTask): string {
  const percent = task.progress === null ? '' : ` ${Math.round(task.progress * 100)}%`;
  if (task.phase === 'downloading') return `下载中${percent}`;
  if (task.phase === 'extracting') return `解压中${percent}`;
  return phaseLabels[task.phase];
}
