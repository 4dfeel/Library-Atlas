import { Unplug } from 'lucide-react';
import { useShell } from '@/app/shell-context';
import { FeedbackState } from '@/components/feedback-state';
import { ApiError, ServiceUnavailableError, useRealSources } from '@/lib/data';

/**
 * Real-mode read failure. An unreachable service, a database that is not ready and a
 * failed query each say what happened; none of them looks like an empty library, and
 * none falls back to demo data.
 */
export function ReadFailure({ error, onRetry }: { error: Error; onRetry: () => void }) {
  if (error instanceof ServiceUnavailableError)
    return (
      <FeedbackState
        kind="error"
        icon={Unplug}
        eyebrow="SERVICE OFFLINE"
        title="本地服务未连接"
        description="Library Atlas 的本地服务没有响应。你的资料没有受到影响；请确认服务已启动，然后重试。"
        action="重新连接"
        onAction={onRetry}
      />
    );
  if (error instanceof ApiError && error.code === 'service_not_ready')
    return (
      <FeedbackState
        kind="error"
        icon={Unplug}
        eyebrow="LIBRARY NOT READY"
        title="资料库暂时不可用"
        description={error.message}
        action="重新检查"
        onAction={onRetry}
      />
    );
  return (
    <FeedbackState
      kind="error"
      title="暂时未能读取资料"
      description={error instanceof ApiError ? error.message : '读取没有成功，你的资料没有变化。'}
      action="重新加载"
      onAction={onRetry}
    />
  );
}

/** A real library with nothing in it. Never filled with samples. */
export function RealLibraryEmpty() {
  const { openSources } = useShell();
  const dlsite = useRealSources().data?.find((source) => source.id === 'dlsite');
  const connected = dlsite?.connection === 'connected' || dlsite?.connection === 'unverified';
  return (
    <FeedbackState
      kind="empty"
      eyebrow="YOUR LIBRARY"
      title="你的作品库还是空的"
      description={
        connected
          ? 'DLsite 已连接。作品同步将在后续版本开放，开放后你拥有的作品会出现在这里；这里不会放入演示作品。'
          : '还没有连接来源，所以这里没有作品。作品同步开放后，你拥有的作品会出现在这里；这里不会放入演示作品。'
      }
      action={connected ? '查看来源状态' : '连接 DLsite'}
      onAction={openSources}
    />
  );
}
