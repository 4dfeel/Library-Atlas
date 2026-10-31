import { CircleAlert, CircleCheck, LoaderCircle, RefreshCw, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { isSyncActive, useDlsiteSync, type SyncJob } from '@/lib/data';
import { formatDate } from '@/lib/utils';

function count(value: number) {
  return value.toLocaleString('zh-CN');
}

function Progress({ job }: { job: SyncJob }) {
  const known = job.total !== null && job.total > 0;
  const percent = known ? Math.round((job.processed / job.total!) * 100) : null;
  return (
    <div className="dlsite-sync-progress" role="status" data-testid="sync-progress">
      <span>
        <LoaderCircle size={14} className="spin" />
        {job.total === null
          ? '正在读取作品列表…'
          : `正在读取作品资料：${count(job.processed)} / ${count(job.total)}`}
      </span>
      {/* Until the total is known the bar moves without pretending to a number. */}
      <div
        className={`task-progress${known ? '' : ' is-indeterminate'}`}
        role="progressbar"
        aria-label="同步进度"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent ?? undefined}
      >
        <span style={known ? { width: `${percent}%` } : undefined} />
      </div>
    </div>
  );
}

function Result({ job }: { job: SyncJob }) {
  if (job.state === 'succeeded')
    return (
      <p className="dlsite-sync-result" role="status" data-testid="sync-result">
        <CircleCheck size={14} />
        同步完成：共 {count(job.total ?? 0)} 部，新增 {count(job.added)}，更新 {count(job.updated)}
        {job.missing > 0 && `，${count(job.missing)} 部平台未返回资料`}。
      </p>
    );
  if (job.state === 'cancelled' && job.code === 'cancelled')
    return (
      <p className="dlsite-note" role="status" data-testid="sync-result">
        已取消，读取到 {count(job.processed)} 部并已保留。
      </p>
    );
  return (
    <p className="dlsite-message" role="alert" data-testid="sync-result">
      <CircleAlert size={14} />
      <span>
        {job.message ?? '同步没有完成。'}
        {job.processed > 0 && ` 已保存 ${count(job.processed)} 部。`}
      </span>
    </p>
  );
}

/** Reads the user's works when they ask. Only metadata: nothing is downloaded. */
export function DlsiteSyncPanel() {
  const { status, start, cancel, error } = useDlsiteSync();
  const job = status?.job;
  const active = job ? isSyncActive(job) : false;
  const last = formatDate(status?.lastSyncedAt ?? null);
  return (
    <div className="dlsite-sync" data-testid="dlsite-sync">
      {job && active && <Progress job={job} />}
      {job && !active && <Result job={job} />}
      {error && (
        <p className="dlsite-message" role="alert">
          <CircleAlert size={14} />
          {error}
        </p>
      )}
      <div className="dlsite-actions">
        {active ? (
          <Button variant="ghost" size="sm" onClick={cancel}>
            <X size={14} />
            取消同步
          </Button>
        ) : (
          <Button size="sm" onClick={start}>
            <RefreshCw size={14} />
            {status?.lastSyncedAt ? '重新同步' : '同步作品库'}
          </Button>
        )}
      </div>
      <p className="dlsite-note">
        {last ? `上次完整同步 ${last}。` : ''}只读取作品资料，不会下载文件。范围是 DLsite Play
        可访问的已购作品。
      </p>
    </div>
  );
}
