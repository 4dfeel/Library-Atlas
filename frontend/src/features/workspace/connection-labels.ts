import type { SourceStatus } from '@/lib/data';

export type ConnectionState =
  'connected' | 'connecting' | 'unverified' | 'expired' | 'error' | 'disconnected';

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
