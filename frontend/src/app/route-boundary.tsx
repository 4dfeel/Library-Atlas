import { Component, type ReactNode } from 'react';
import { FeedbackState } from '@/components/feedback-state';

/**
 * A page module that cannot load (the local service stopped before it was first opened)
 * or a page that throws must not blank the whole app. Keyed by route, so moving to
 * another page starts clean.
 */
export class RouteBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  override state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  override render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main className="detail-page detail-feedback" data-testid="route-failure">
        <FeedbackState
          kind="error"
          title="这个页面暂时打不开"
          description="页面内容没有加载成功。如果本地服务刚才停止了，请确认它已重新启动，然后重新加载。你的资料没有受到影响。"
          action="重新加载页面"
          onAction={() => window.location.reload()}
        />
      </main>
    );
  }
}
