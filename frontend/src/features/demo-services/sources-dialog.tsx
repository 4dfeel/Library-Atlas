import { CircleAlert, Clock3, Link2, LoaderCircle, PlugZap, Unplug } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import {
  demoConnections,
  useConnections,
  useDashboard,
  useRealSources,
  type DemoSize,
  type ConnectionState,
  type Platform,
  type SourceConnection,
  type SourceStatus,
} from '@/lib/data';
import { platformLabels } from '@/lib/utils';
import { connectionLabels, realConnectionState } from './labels';

const timeFormat = new Intl.DateTimeFormat('zh-CN', {
  month: 'long',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
});

function RealSourceRow({ platform, source }: { platform: Platform; source?: SourceStatus }) {
  const name = platformLabels[platform];
  return (
    <section className="source-row" aria-labelledby={`source-${platform}`} data-source={platform}>
      <div className="source-row-heading">
        <span className={`source-mark source-${platform}`} aria-hidden="true">
          {name.slice(0, 1)}
        </span>
        <div>
          <h3 id={`source-${platform}`}>{name}</h3>
          <p>连接与同步将在后续版本开放。</p>
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
          <dd>暂无记录</dd>
        </div>
      </dl>
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

function SourceRow({
  connection,
  works,
}: {
  connection: SourceConnection;
  works: number | undefined;
}) {
  const platform: Platform = connection.platform;
  const name = platformLabels[platform];
  const { state } = connection;
  return (
    <section className="source-row" aria-labelledby={`source-${platform}`} data-source={platform}>
      <div className="source-row-heading">
        <span className={`source-mark source-${platform}`} aria-hidden="true">
          {name.slice(0, 1)}
        </span>
        <div>
          <h3 id={`source-${platform}`}>{name}</h3>
          <p>
            {state === 'connected' && connection.alias
              ? connection.alias
              : state === 'disconnected'
                ? '连接后可导入你已拥有的作品'
                : state === 'expired'
                  ? '演示会话已过期，需要重新连接后才能同步'
                  : state === 'error'
                    ? '演示连接失败，可以重试'
                    : '正在建立演示连接…'}
          </p>
        </div>
        <ConnectionBadge state={state} />
      </div>
      <dl className="source-facts">
        <div>
          <dt>本地作品</dt>
          <dd>{works === undefined ? '—' : `${works.toLocaleString('zh-CN')} 部`}</dd>
        </div>
        <div>
          <dt>最后演示同步</dt>
          <dd>
            {connection.lastSyncAt ? (
              <>
                <Clock3 size={12} />
                {timeFormat.format(new Date(connection.lastSyncAt))}
              </>
            ) : (
              '暂无记录'
            )}
          </dd>
        </div>
      </dl>
      {state !== 'connected' && state !== 'connecting' && (
        <p className="source-keep-note">
          断开或过期不会删除本地作品，已导入的作品继续保留并可浏览。
        </p>
      )}
      <div className="source-actions">
        {state === 'connected' && (
          <>
            <Button variant="secondary" size="sm" onClick={() => demoConnections.expire(platform)}>
              <Clock3 size={14} />
              模拟会话过期
            </Button>
            <Button variant="ghost" size="sm" onClick={() => demoConnections.disconnect(platform)}>
              <Unplug size={14} />
              断开（演示）
            </Button>
          </>
        )}
        {(state === 'disconnected' || state === 'expired' || state === 'error') && (
          <>
            <Button size="sm" onClick={() => demoConnections.connect(platform)}>
              <Link2 size={14} />
              {state === 'disconnected'
                ? '演示连接'
                : state === 'expired'
                  ? '重新连接（演示）'
                  : '重试（演示）'}
            </Button>
            {!connection.failNext && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => demoConnections.failNextConnect(platform)}
              >
                <CircleAlert size={14} />
                下次连接模拟失败
              </Button>
            )}
            {connection.failNext && <span className="source-hint">下次连接将模拟失败</span>}
            {state !== 'disconnected' && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => demoConnections.disconnect(platform)}
              >
                <Unplug size={14} />
                断开（演示）
              </Button>
            )}
          </>
        )}
      </div>
    </section>
  );
}

export function SourcesDialog({
  open,
  onOpenChange,
  size,
  demoEnabled,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  size: DemoSize;
  demoEnabled: boolean;
}) {
  const connections = useConnections();
  // Same cached, privacy-filtered snapshot the Dashboard uses.
  const sources = useDashboard('all', { size, enabled: demoEnabled }).data?.sources;
  const real = useRealSources(open && !demoEnabled);
  const counts = sources && { steam: sources.steam.works, dlsite: sources.dlsite.works };
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="来源连接"
      description={
        demoEnabled
          ? '仅演示：不会要求、接收或保存任何密码、Cookie 或令牌。真实连接将在后续阶段由你在平台官方页面登录完成。'
          : '真实连接将在后续阶段由你在平台官方页面登录完成；不会要求、接收或保存任何密码。'
      }
    >
      {demoEnabled ? (
        <div className="sources-dialog">
          <SourceRow connection={connections.steam} works={counts?.steam} />
          <SourceRow connection={connections.dlsite} works={counts?.dlsite} />
          <p className="dialog-footnote">
            <PlugZap size={14} />
            状态保存在本浏览器的演示存储中，与未来真实会话完全隔离。
          </p>
        </div>
      ) : real.isError ? (
        <p className="service-unavailable" role="alert">
          <PlugZap size={16} />
          本地服务没有响应，暂时无法读取来源状态。
        </p>
      ) : (
        // Demo sessions are never shown as real connections.
        <div className="sources-dialog" data-testid="real-sources">
          {(['steam', 'dlsite'] as const).map((platform) => (
            <RealSourceRow
              key={platform}
              platform={platform}
              source={real.data?.find((source) => source.id === platform)}
            />
          ))}
          <p className="dialog-footnote">
            <PlugZap size={14} />
            真实来源连接尚未接入，Steam 与 DLsite 均未连接。
          </p>
        </div>
      )}
    </Dialog>
  );
}
