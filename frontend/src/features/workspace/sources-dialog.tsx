import { LoaderCircle, PlugZap } from 'lucide-react';
import { Dialog } from '@/components/ui/dialog';
import { useRealSources, type Platform, type SourceStatus } from '@/lib/data';
import { formatDate, platformLabels } from '@/lib/utils';
import { connectionLabels, realConnectionState, type ConnectionState } from './connection-labels';
import { DlsiteConnectionPanel } from './dlsite-connection';

function RealSourceRow({ platform, source }: { platform: Platform; source?: SourceStatus }) {
  const name = platformLabels[platform];
  const synced = formatDate(source?.lastSyncAt ?? null);
  return (
    <section className="source-row" aria-labelledby={`source-${platform}`} data-source={platform}>
      <div className="source-row-heading">
        <span className={`source-mark source-${platform}`} aria-hidden="true">
          {name.slice(0, 1)}
        </span>
        <div>
          <h3 id={`source-${platform}`}>{name}</h3>
          <p>
            {platform === 'dlsite' ? '在这里登录，全程不用离开 Atlas。' : '连接将在后续版本开放。'}
          </p>
        </div>
        <ConnectionBadge state={realConnectionState(source)} />
      </div>
      <dl className="source-facts">
        <div>
          <dt>本地作品</dt>
          <dd>{source ? `${source.workCount.toLocaleString('zh-CN')} 部` : '—'}</dd>
        </div>
        <div>
          <dt>最后同步</dt>
          <dd>{synced ?? '暂无记录'}</dd>
        </div>
      </dl>
      {platform === 'dlsite' && <DlsiteConnectionPanel />}
    </section>
  );
}

export function ConnectionBadge({ state }: { state: ConnectionState }) {
  return (
    <span className={`connection-badge connection-${state}`}>
      {state === 'connecting' ? <LoaderCircle size={12} className="spin" /> : <i />}
      {connectionLabels[state]}
    </span>
  );
}

export function SourcesDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const real = useRealSources(open);
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="来源连接"
      description="登录后的会话保存在 Windows 凭据管理器。只有你选择记住时，才会同时保存账号密码。"
    >
      {real.isError ? (
        <p className="service-unavailable" role="alert">
          <PlugZap size={16} />
          本地服务没有响应，暂时无法读取来源状态。
        </p>
      ) : (
        <div className="sources-dialog" data-testid="real-sources">
          {(['steam', 'dlsite'] as const).map((platform) => (
            <RealSourceRow
              key={platform}
              platform={platform}
              source={real.data?.find((source) => source.id === platform)}
            />
          ))}
        </div>
      )}
    </Dialog>
  );
}
