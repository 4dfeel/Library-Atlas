import { useEffect, useState, type ReactNode } from 'react';
import {
  CircleAlert,
  CircleCheck,
  Download,
  FileArchive,
  FolderOpen,
  Gauge,
  Pause,
  Play,
  RotateCcw,
  X,
} from 'lucide-react';
import { AppLink } from '@/components/app-link';
import { Button } from '@/components/ui/button';
import {
  isDownloadActive,
  isExtractActive,
  useDownloadActions,
  useDownloads,
  useExtractionActions,
  useExtractions,
  useUpdateSettings,
  type DemoSize,
  type DownloadTask,
  type ExtractTask,
} from '@/lib/data';
import { downloadsHref, gameHref, navigate } from '@/lib/router';
import { formatBytes } from '@/lib/utils';
import { amount, extractLabels, messageOf, stateLabels } from './labels';
import { Progress } from './real-downloads';

const coverOf = (workId: string) => `/api/v1/works/${encodeURIComponent(workId)}/cover`;

function formatSpeed(bytes: number) {
  return `${formatBytes(Math.max(bytes, 1024))}/s`;
}

function formatRemaining(seconds: number) {
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))} 秒`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} 分 ${Math.round(seconds % 60)} 秒`;
  return `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分`;
}

/** The cover if there is one; a missing cover quietly becomes a plain tile. */
function Cover({ workId, className }: { workId: string; className: string }) {
  const [failed, setFailed] = useState(false);
  if (failed)
    return (
      <span className={`${className} is-empty`} aria-hidden="true">
        <Download size={20} />
      </span>
    );
  return (
    <img
      className={className}
      src={coverOf(workId)}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}

/** The transfer in front, as in Steam: what it is, how fast, and how far along. */
function Current({
  task,
  extraction,
  size,
}: {
  task: DownloadTask | undefined;
  extraction: ExtractTask | undefined;
  size: DemoSize;
}) {
  const actions = useDownloadActions();
  const unpacking = useExtractionActions();
  const taskId = task?.id;
  const speed = task?.bytesPerSecond ?? null;
  const [peak, setPeak] = useState({ taskId, value: 0 });
  if (peak.taskId !== taskId) setPeak({ taskId, value: 0 });
  else if (speed !== null && speed > peak.value) setPeak({ taskId, value: speed });
  const workId = task?.workId ?? extraction?.workId;
  const title = task?.title ?? extraction?.title;
  if (!workId)
    return (
      <section className="downloads-current is-idle" data-testid="downloads-idle">
        <Download size={22} />
        <span>现在没有进行中的下载。</span>
      </section>
    );
  const remaining =
    task && speed && task.bytesTotal !== null
      ? (task.bytesTotal - task.bytesDone) / Math.max(speed, 1)
      : null;
  return (
    <section className="downloads-current" data-testid="downloads-current">
      <Cover workId={workId} className="downloads-current-cover" />
      <div className="downloads-current-title">
        <AppLink to={gameHref(workId, size)} title={title}>
          {title}
        </AppLink>
        {task?.part !== null && task?.part !== undefined && (
          <span>
            第 {task.part}/{task.partCount ?? '?'} 个文件
          </span>
        )}
      </div>
      <div className="downloads-current-numbers">
        {task && (
          <dl className="downloads-stats">
            <div>
              <dt>
                <Gauge size={13} />
                网络
              </dt>
              <dd data-testid="downloads-speed">{speed === null ? '—' : formatSpeed(speed)}</dd>
            </div>
            <div>
              <dt>
                <Gauge size={13} />
                峰值
              </dt>
              <dd>{peak.value ? formatSpeed(peak.value) : '—'}</dd>
            </div>
          </dl>
        )}
        {task && (
          <div className="downloads-line">
            <span>{stateLabels[task.state]}</span>
            <span>{amount(task.bytesDone, task.bytesTotal)}</span>
            <Progress
              done={task.bytesDone}
              total={task.bytesTotal}
              label={stateLabels[task.state]}
            />
          </div>
        )}
        {extraction && (
          <div className="downloads-line is-extract">
            <span>{extractLabels[extraction.state]}</span>
            <span>
              {extraction.state === 'extracting' && extraction.bytesTotal
                ? amount(extraction.bytesDone, extraction.bytesTotal)
                : ''}
            </span>
            <Progress
              done={extraction.bytesDone}
              total={extraction.state === 'extracting' ? extraction.bytesTotal : null}
              label={extractLabels[extraction.state]}
            />
          </div>
        )}
        <div className="downloads-current-actions">
          <span className="downloads-current-remaining">
            {remaining !== null && `估计剩余时间：${formatRemaining(remaining)}`}
          </span>
          {task?.state === 'downloading' && (
            <Button
              size="sm"
              aria-label="暂停"
              onClick={() => void actions.act(task.id, 'pause').catch(() => undefined)}
            >
              <Pause size={14} />
              暂停
            </Button>
          )}
          {task && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => void actions.act(task.id, 'cancel').catch(() => undefined)}
            >
              <X size={14} />
              取消
            </Button>
          )}
          {!task && extraction && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => void unpacking.act(extraction.id, 'cancel').catch(() => undefined)}
            >
              <X size={14} />
              取消解压
            </Button>
          )}
        </div>
      </div>
    </section>
  );
}

function Row({
  workId,
  title,
  detail,
  status,
  statusIcon,
  error,
  progress,
  actions,
  size,
  testId,
}: {
  workId: string;
  title: string;
  detail: ReactNode;
  status: string;
  statusIcon?: ReactNode;
  error?: string | null;
  progress?: ReactNode;
  actions: ReactNode;
  size: DemoSize;
  testId: Record<string, string>;
}) {
  return (
    <li className="queue-row" {...testId}>
      <Cover workId={workId} className="queue-row-cover" />
      <div className="queue-row-main">
        <AppLink to={gameHref(workId, size)} className="queue-row-title" title={title}>
          {title}
        </AppLink>
        <span className="queue-row-detail">{detail}</span>
        {error && <span className="save-error">{error}</span>}
        {progress}
      </div>
      <span className="queue-row-status" aria-live="polite">
        {statusIcon}
        {status}
      </span>
      <span className="queue-row-actions">{actions}</span>
    </li>
  );
}

function DownloadRow({ task, size }: { task: DownloadTask; size: DemoSize }) {
  const actions = useDownloadActions();
  const [error, setError] = useState<string | null>(null);
  const act = (action: 'cancel' | 'pause' | 'retry' | 'open-folder') => () => {
    setError(null);
    actions.act(task.id, action).catch((failure: unknown) => setError(messageOf(failure)));
  };
  const active = isDownloadActive(task);
  const done = task.state === 'done';
  return (
    <Row
      workId={task.workId}
      title={`${task.title}${task.part !== null ? ` · 第 ${task.part}/${task.partCount ?? '?'} 个文件` : ''}`}
      size={size}
      testId={{ 'data-download-task': task.id }}
      status={stateLabels[task.state]}
      statusIcon={
        done ? (
          <CircleCheck size={14} />
        ) : task.state === 'failed' ? (
          <CircleAlert size={14} />
        ) : undefined
      }
      detail={
        <>
          {done
            ? task.bytesDone
              ? formatBytes(task.bytesDone)
              : ''
            : amount(task.bytesDone, task.bytesTotal)}
          {done && task.fileName && (
            <span className="download-path" title={task.location ?? undefined}>
              {task.fileName}
            </span>
          )}
          {done && task.integrity === 'stream_end' && (
            <span title="服务器没有说明文件大小，只能确认传输正常结束。">完整性保障有限</span>
          )}
          {task.fileMissing && <span className="save-error">文件已经不在原位置</span>}
        </>
      }
      error={error ?? (task.state !== 'cancelled' ? task.message : null)}
      progress={
        active && task.state !== 'paused' ? (
          <Progress done={task.bytesDone} total={task.bytesTotal} label={stateLabels[task.state]} />
        ) : undefined
      }
      actions={
        <>
          {task.state === 'downloading' && (
            <Button variant="ghost" size="sm" onClick={act('pause')}>
              <Pause size={14} />
              暂停
            </Button>
          )}
          {task.canRetry && (
            <Button variant="secondary" size="sm" onClick={act('retry')}>
              {task.canResume ? <Play size={14} /> : <RotateCcw size={14} />}
              {task.canResume ? '继续' : '重新下载'}
            </Button>
          )}
          {(active || task.canRetry) && task.state !== 'cancelled' && (
            <Button variant="ghost" size="sm" onClick={act('cancel')}>
              <X size={14} />
              取消
            </Button>
          )}
          {done && !task.fileMissing && (
            <Button variant="ghost" size="sm" onClick={act('open-folder')}>
              <FolderOpen size={14} />
              打开压缩包位置
            </Button>
          )}
        </>
      }
    />
  );
}

function ExtractRow({ task, size }: { task: ExtractTask; size: DemoSize }) {
  const unpacking = useExtractionActions();
  const [error, setError] = useState<string | null>(null);
  const act = (action: 'cancel' | 'retry' | 'open-folder') => () => {
    setError(null);
    unpacking.act(task.id, action).catch((failure: unknown) => setError(messageOf(failure)));
  };
  const active = isExtractActive(task);
  const done = task.state === 'done';
  return (
    <Row
      workId={task.workId}
      title={task.title}
      size={size}
      testId={{ 'data-extract-task': task.id }}
      status={done && task.format === 'file' ? '已放入作品文件夹' : extractLabels[task.state]}
      statusIcon={
        done ? (
          <CircleCheck size={14} />
        ) : task.state === 'failed' ? (
          <CircleAlert size={14} />
        ) : (
          <FileArchive size={14} />
        )
      }
      detail={
        <>
          {task.filesTotal !== null &&
            `${task.filesTotal} 个文件${task.bytesTotal !== null ? ` · ${formatBytes(task.bytesTotal)}` : ''}`}
          {task.resultMissing && <span className="save-error">解压结果已经不在原位置</span>}
          {task.cleanupFailed && (
            <span className="save-error">
              有临时文件没能删除，可以手动删除作品文件夹里以 .atlas-extract- 开头的文件夹
            </span>
          )}
        </>
      }
      error={error ?? (task.state !== 'cancelled' ? task.message : null)}
      progress={
        active ? (
          <Progress
            done={task.bytesDone}
            total={task.state === 'extracting' ? task.bytesTotal : null}
            label={extractLabels[task.state]}
          />
        ) : undefined
      }
      actions={
        <>
          {task.canRetry && (
            <Button variant="secondary" size="sm" onClick={act('retry')}>
              <RotateCcw size={14} />
              重新解压
            </Button>
          )}
          {active && (
            <Button variant="ghost" size="sm" onClick={act('cancel')}>
              <X size={14} />
              取消
            </Button>
          )}
          {done && !task.resultMissing && (
            <Button variant="ghost" size="sm" onClick={act('open-folder')}>
              <FolderOpen size={14} />
              打开作品文件夹
            </Button>
          )}
        </>
      }
    />
  );
}

function Section({
  title,
  count,
  aside,
  empty,
  children,
}: {
  title: string;
  count: number;
  aside?: ReactNode;
  empty?: string;
  children?: ReactNode;
}) {
  return (
    <section className="downloads-section">
      <header>
        <h2>
          {title} <span>({count})</span>
        </h2>
        <i aria-hidden="true" />
        {aside}
      </header>
      {count > 0 ? <ul className="queue-list">{children}</ul> : empty && <p>{empty}</p>}
    </section>
  );
}

function AutoCheck() {
  const { settings, setAuto } = useUpdateSettings();
  if (!settings) return null;
  return (
    <label className="downloads-auto" data-testid="auto-check">
      <input
        type="checkbox"
        checked={settings.autoCheck}
        onChange={(event) => setAuto(event.target.checked)}
      />
      每天自动检查更新
    </label>
  );
}

function UpdateRow({ workId, title, size }: { workId: string; title: string; size: DemoSize }) {
  const actions = useDownloadActions();
  const [error, setError] = useState<string | null>(null);
  return (
    <Row
      workId={workId}
      title={title}
      size={size}
      testId={{ 'data-update': workId }}
      status="有新版本"
      detail="DLsite 上的这部作品更新过。下载后旧文件仍然保留。"
      error={error}
      actions={
        <Button
          variant="secondary"
          size="sm"
          onClick={() => {
            setError(null);
            actions
              .create(workId, null, true, false)
              .catch((failure: unknown) => setError(messageOf(failure)));
          }}
        >
          <Download size={14} />
          下载更新
        </Button>
      }
    />
  );
}

/** The full queue, kept by the service: leaving this page or the browser stops nothing. */
export function DownloadsPage({ size }: { size: DemoSize }) {
  const { tasks, updates, failed: unreachable } = useDownloads();
  const { tasks: extractions } = useExtractions();
  const actions = useDownloadActions();
  const unpacking = useExtractionActions();
  useEffect(() => {
    document.title = '下载 · Library Atlas';
  }, []);

  const current =
    tasks.find((task) => task.state === 'downloading') ??
    tasks.find((task) => task.state === 'verifying' || task.state === 'resolving');
  const currentExtraction = extractions.find(isExtractActive);
  const waiting = tasks.filter(
    (task) => task.id !== current?.id && task.state !== 'done' && task.state !== 'cancelled',
  );
  const waitingExtractions = extractions.filter(
    (task) =>
      task.id !== currentExtraction?.id &&
      (task.state === 'failed' || task.state === 'interrupted' || task.state === 'queued'),
  );
  const finished = tasks.filter((task) => task.state === 'done' || task.state === 'cancelled');
  const finishedExtractions = extractions.filter(
    (task) => task.state === 'done' || task.state === 'not_needed' || task.state === 'cancelled',
  );
  const clearable =
    tasks.some((task) => task.state === 'cancelled' || task.state === 'failed') ||
    extractions.some((task) => task.state === 'cancelled' || task.state === 'failed');

  return (
    <main className="detail-page downloads-page" data-testid="downloads-page">
      <h1 className="sr-only">下载</h1>
      <Current task={current} extraction={currentExtraction} size={size} />
      <div className="detail-frame downloads-frame">
        {unreachable && (
          <p className="service-unavailable" role="alert">
            <CircleAlert size={16} />
            本地服务没有响应，暂时无法读取下载任务。
          </p>
        )}
        <Section title="有更新" count={updates.length} aside={<AutoCheck />}>
          {updates.map((update) => (
            <UpdateRow
              key={update.workId}
              workId={update.workId}
              title={update.title}
              size={size}
            />
          ))}
        </Section>
        <Section
          title="即将进行"
          count={waiting.length + waitingExtractions.length}
          empty="队列中没有任务。打开一部 DLsite 作品，点“下载并解压”。"
        >
          {waitingExtractions.map((task) => (
            <ExtractRow key={task.id} task={task} size={size} />
          ))}
          {waiting.map((task) => (
            <DownloadRow key={task.id} task={task} size={size} />
          ))}
        </Section>
        <Section
          title="已完成"
          count={finished.length + finishedExtractions.length}
          aside={
            clearable ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void Promise.all([actions.clear(), unpacking.clear()])}
              >
                清除已取消和失败的任务
              </Button>
            ) : undefined
          }
        >
          {finishedExtractions.map((task) => (
            <ExtractRow key={task.id} task={task} size={size} />
          ))}
          {finished.map((task) => (
            <DownloadRow key={task.id} task={task} size={size} />
          ))}
        </Section>
      </div>
    </main>
  );
}

/** Always at the bottom of the real library, as in Steam. One click opens the queue. */
export function DownloadBar() {
  const { tasks } = useDownloads();
  const { tasks: extractions } = useExtractions();
  const running = tasks.find((task) => task.state === 'downloading');
  const counted = tasks.filter((task) => task.state !== 'cancelled');
  const finished = counted.filter((task) => task.state === 'done').length;
  const unpacking = extractions.find(isExtractActive);
  const queued = tasks.some(isDownloadActive);

  let text = '下载';
  if (running) {
    text = `下载中 - ${running.title} · ${amount(running.bytesDone, running.bytesTotal)}`;
    if (running.bytesPerSecond) text += ` · ${formatSpeed(running.bytesPerSecond)}`;
  } else if (unpacking) {
    text = `解压中 - ${unpacking.title}`;
  } else if (counted.length) {
    text = `下载 - ${counted.length} 个项目中的 ${finished} 项已完成`;
  }
  const known = running && running.bytesTotal ? running.bytesDone / running.bytesTotal : null;
  return (
    <button
      type="button"
      className={`download-bar${running || unpacking || queued ? ' is-active' : ''}`}
      data-testid="download-bar"
      onClick={() => navigate(downloadsHref())}
    >
      {known !== null && (
        <span className="download-bar-fill" style={{ width: `${Math.round(known * 100)}%` }} />
      )}
      <Download size={15} />
      <span className="download-bar-text" title={text}>
        {text}
      </span>
    </button>
  );
}
