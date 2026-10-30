import { useState } from 'react';
import {
  CircleAlert,
  CircleCheck,
  Download,
  FolderOpen,
  FolderSearch,
  LoaderCircle,
  Pause,
  Play,
  RotateCcw,
  X,
} from 'lucide-react';
import { useShell } from '@/app/shell-context';
import { AppLink } from '@/components/app-link';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import {
  isDownloadActive,
  useDownloadActions,
  useDownloads,
  useFolderActions,
  type DemoSize,
  type DownloadPlan,
  type DownloadTask,
  type GameDetail,
} from '@/lib/data';
import { gameHref } from '@/lib/router';
import { formatBytes } from '@/lib/utils';

const stateLabels: Record<DownloadTask['state'], string> = {
  queued: '排队中',
  resolving: '正在获取下载地址',
  downloading: '下载中',
  verifying: '校验中',
  paused: '已暂停',
  done: '已下载',
  failed: '下载失败',
  cancelled: '已取消',
  reauth_required: '需要重新登录',
  interrupted: '已中断',
};

const EXTRACT_NOTE = '解压将在后续版本开放。已下载不代表已安装或可以运行。';

function messageOf(error: unknown) {
  return error instanceof Error ? error.message : '操作没有完成，请重试。';
}

function amount(done: number, total: number | null) {
  return total === null
    ? `已下载 ${formatBytes(done)} · 总大小未知`
    : `${formatBytes(done)} / ${formatBytes(total)}`;
}

/** Real bytes against a real total; without a total the bar moves and claims no number. */
function Progress({ done, total, label }: { done: number; total: number | null; label: string }) {
  const known = total !== null && total > 0;
  const percent = known ? Math.min(100, Math.round((done / total) * 100)) : null;
  return (
    <div
      className={`task-progress${known ? '' : ' is-indeterminate'}`}
      role="progressbar"
      aria-label={`${label}进度`}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent ?? undefined}
      aria-valuetext={percent === null ? `${label}，总大小未知` : `${percent}%`}
    >
      <span style={known ? { width: `${percent}%` } : undefined} />
    </div>
  );
}

/** Asked only when a choice is really needed: parts to pick, or no folder yet. */
function PlanDialog({
  game,
  plan,
  onClose,
  onReplan,
  onStart,
  error,
  starting,
}: {
  game: GameDetail;
  plan: DownloadPlan;
  onClose: () => void;
  onReplan: () => void;
  onStart: (parts: number[] | null) => void;
  error: string | null;
  starting: boolean;
}) {
  const [chosen, setChosen] = useState<Set<number>>(() => new Set(plan.parts));
  const { pick } = useFolderActions('library');
  const folderReady = plan.folder.status === 'ok';
  const tooBig =
    plan.totalBytes !== null && plan.freeBytes !== null && plan.totalBytes > plan.freeBytes;
  const split = plan.kind === 'split';
  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onClose()}
      title="下载作品"
      description={game.title}
    >
      <div className="download-plan" data-testid="download-plan">
        <section>
          <h3>保存到</h3>
          {plan.folder.path ? (
            <p className="download-path" title={plan.folder.path}>
              {plan.folder.path}
            </p>
          ) : (
            <p className="settings-note">
              还没有选择作品文件夹。文件会放在里面以作品编号命名的子文件夹中。
            </p>
          )}
          {plan.folder.status === 'missing' && (
            <p className="dlsite-message" role="alert">
              <CircleAlert size={14} />
              这个文件夹现在不存在，可能是硬盘没有连接。Atlas 不会自动重建它。
            </p>
          )}
          <Button
            variant="secondary"
            size="sm"
            disabled={pick.isPending}
            onClick={() => pick.mutate(undefined, { onSuccess: onReplan })}
          >
            {pick.isPending ? (
              <LoaderCircle size={14} className="spin" />
            ) : (
              <FolderSearch size={14} />
            )}
            {plan.folder.path ? '更改文件夹' : '选择文件夹'}
          </Button>
          {pick.error && (
            <p className="dlsite-message" role="alert">
              <CircleAlert size={14} />
              {pick.error.message}
            </p>
          )}
        </section>
        {split && (
          <section>
            <h3>文件</h3>
            <p className="settings-note">
              这部作品分成 {plan.parts.length} 个文件，通常要全部下载才能使用。
            </p>
            <ul className="download-parts">
              {plan.parts.map((part) => (
                <li key={part}>
                  <label>
                    <input
                      type="checkbox"
                      checked={chosen.has(part)}
                      onChange={(event) => {
                        const next = new Set(chosen);
                        if (event.target.checked) next.add(part);
                        else next.delete(part);
                        setChosen(next);
                      }}
                    />
                    第 {part} 个文件
                  </label>
                </li>
              ))}
            </ul>
          </section>
        )}
        <p className="settings-note">
          {plan.totalBytes === null
            ? '平台没有提供大小，无法预估需要多少空间。'
            : `平台标注的大小：${formatBytes(plan.totalBytes)}`}
          {plan.freeBytes !== null && ` · 可用空间 ${formatBytes(plan.freeBytes)}`}
        </p>
        {tooBig && (
          <p className="dlsite-message" role="alert">
            <CircleAlert size={14} />
            可用空间可能不够。
          </p>
        )}
        {error && (
          <p className="dlsite-message" role="alert">
            <CircleAlert size={14} />
            {error}
          </p>
        )}
        <div className="dlsite-actions">
          <Button
            size="sm"
            disabled={!folderReady || starting || (split && chosen.size === 0)}
            onClick={() => onStart(split ? [...chosen].sort((a, b) => a - b) : null)}
          >
            {starting ? <LoaderCircle size={14} className="spin" /> : <Download size={14} />}
            开始下载
          </Button>
          <Button variant="ghost" size="sm" onClick={onClose}>
            取消
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

/** The real entry on a work's page. Nothing is requested until the user presses it. */
export function RealDownloadAction({ game }: { game: GameDetail }) {
  const { openTasks } = useShell();
  const { tasks } = useDownloads();
  const actions = useDownloadActions();
  const [plan, setPlan] = useState<DownloadPlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const mine = tasks.filter((task) => task.workId === game.id);
  const active = mine.filter(isDownloadActive);
  const finished = mine.filter((task) => task.state === 'done' && !task.fileMissing);
  const troubled = mine.filter((task) => task.message && task.state !== 'cancelled');

  const start = async (parts: number[] | null, again = false) => {
    setBusy(true);
    setError(null);
    try {
      await actions.create(game.id, parts, again);
      setPlan(null);
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy(false);
    }
  };

  const begin = async (again = false) => {
    setBusy(true);
    setError(null);
    try {
      const next = await actions.plan(game.id);
      if (next.kind === 'serial') {
        setError('这部作品需要序列号，暂不支持在 Atlas 内下载。');
      } else if (next.kind === 'direct' && next.folder.status === 'ok') {
        await actions.create(game.id, null, again);
      } else {
        setPlan(next);
      }
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy(false);
    }
  };

  const replan = () => {
    actions
      .plan(game.id)
      .then(setPlan)
      .catch((failure: unknown) => setError(messageOf(failure)));
  };

  const dialog = plan && (
    <PlanDialog
      key={`${plan.kind}:${plan.parts.length}`}
      game={game}
      plan={plan}
      onClose={() => setPlan(null)}
      onReplan={replan}
      onStart={(parts) => void start(parts)}
      error={error}
      starting={busy}
    />
  );

  if (active.length) {
    const done = active.reduce((sum, task) => sum + task.bytesDone, 0);
    const unknown = active.some((task) => task.bytesTotal === null);
    const total = unknown ? null : active.reduce((sum, task) => sum + (task.bytesTotal ?? 0), 0);
    const lead = active.find((task) => task.state === 'downloading') ?? active[0]!;
    return (
      <div className="hero-download" data-testid="download-action" aria-live="polite">
        <span className="download-state">
          {stateLabels[lead.state]}
          {active.length > 1 && ` · ${active.length} 个文件`} · {amount(done, total)}
        </span>
        <Progress done={done} total={total} label={stateLabels[lead.state]} />
        <Button variant="ghost" size="sm" onClick={openTasks}>
          查看任务
        </Button>
        {error && <span className="download-state is-error">{error}</span>}
      </div>
    );
  }

  return (
    <div className="hero-download" data-testid="download-action" aria-live="polite">
      {finished.length > 0 && troubled.length === 0 ? (
        <>
          <span className="download-state is-done" data-testid="download-done">
            <CircleCheck size={14} />
            已下载 {finished.length > 1 ? `${finished.length} 个文件` : ''}
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void actions.act(finished[0]!.id, 'open-folder').catch(() => undefined)}
          >
            <FolderOpen size={14} />
            打开文件夹
          </Button>
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => void begin(true)}>
            <RotateCcw size={14} />
            重新下载
          </Button>
          <span className="download-note">{EXTRACT_NOTE}</span>
        </>
      ) : troubled.length > 0 ? (
        <>
          <span className="download-state is-error">
            <CircleAlert size={14} />
            {troubled[0]!.message}
          </span>
          {troubled.some((task) => task.canRetry) && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                for (const task of troubled)
                  if (task.canRetry) void actions.act(task.id, 'retry').catch(() => undefined);
              }}
            >
              <RotateCcw size={14} />
              {troubled.some((task) => task.canResume) ? '继续下载' : '重新下载'}
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={openTasks}>
            查看任务
          </Button>
        </>
      ) : (
        <>
          <Button variant="secondary" size="sm" disabled={busy} onClick={() => void begin()}>
            {busy ? <LoaderCircle size={14} className="spin" /> : <Download size={14} />}
            下载
          </Button>
          <span className="download-note">
            {game.file?.sizeBytes ? formatBytes(game.file.sizeBytes) : '大小未知'}
            {mine.some((task) => task.fileMissing) && ' · 之前下载的文件已经不在原位置'}
          </span>
          {error && !plan && (
            <span className="download-state is-error" role="alert">
              <CircleAlert size={14} />
              {error}
            </span>
          )}
        </>
      )}
      {dialog}
    </div>
  );
}

function TaskRow({ task, size }: { task: DownloadTask; size: DemoSize }) {
  const actions = useDownloadActions();
  const [error, setError] = useState<string | null>(null);
  const act = (action: 'cancel' | 'pause' | 'retry' | 'open-folder') => () => {
    setError(null);
    actions.act(task.id, action).catch((failure: unknown) => setError(messageOf(failure)));
  };
  const active = isDownloadActive(task);
  const running = active && task.state !== 'paused';
  return (
    <li className={`task-row task-${task.state}`} data-download-task={task.id}>
      <div className="task-row-heading">
        <AppLink to={gameHref(task.workId, size)} className="task-title" title={task.title}>
          {task.title}
          {task.part !== null && ` · 第 ${task.part}/${task.partCount ?? '?'} 个文件`}
        </AppLink>
        <span className="task-phase" aria-live="polite">
          {task.state === 'done' ? (
            <CircleCheck size={14} />
          ) : task.state === 'failed' ? (
            <CircleAlert size={14} />
          ) : null}
          {stateLabels[task.state]}
        </span>
      </div>
      {running && (
        <Progress done={task.bytesDone} total={task.bytesTotal} label={stateLabels[task.state]} />
      )}
      <div className="task-meta">
        <span>
          {task.state === 'done'
            ? task.bytesDone
              ? formatBytes(task.bytesDone)
              : ''
            : amount(task.bytesDone, task.bytesTotal)}
        </span>
        {task.state === 'done' && task.fileName && (
          <span className="download-path" title={task.location ?? undefined}>
            {task.fileName}
          </span>
        )}
        {task.state === 'done' && task.integrity === 'stream_end' && (
          <span title="服务器没有说明文件大小，只能确认传输正常结束。">完整性保障有限</span>
        )}
        {task.fileMissing && <span className="save-error">文件已经不在原位置</span>}
        {task.message && task.state !== 'cancelled' && (
          <span className="save-error">{task.message}</span>
        )}
        {error && <span className="save-error">{error}</span>}
        <span className="task-actions">
          {running && task.state === 'downloading' && (
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
          {task.state === 'done' && !task.fileMissing && (
            <Button variant="ghost" size="sm" onClick={act('open-folder')}>
              <FolderOpen size={14} />
              打开文件夹
            </Button>
          )}
        </span>
      </div>
    </li>
  );
}

/** The queue. Kept by the service, so it survives closing this and reloading the page. */
export function RealTasksDialog({
  open,
  onOpenChange,
  size,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  size: DemoSize;
}) {
  const { tasks, failed: unreachable } = useDownloads();
  const actions = useDownloadActions();
  const clearable = tasks.some((task) => task.state === 'cancelled' || task.state === 'failed');
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="下载"
      description="下载在本地服务中进行，关闭页面也不会中断。解压将在后续版本开放。"
    >
      <div className="tasks-dialog">
        {unreachable ? (
          <p className="service-unavailable" role="alert">
            <CircleAlert size={16} />
            本地服务没有响应，暂时无法读取下载任务。
          </p>
        ) : tasks.length ? (
          <ul className="task-list">
            {tasks.map((task) => (
              <TaskRow key={task.id} task={task} size={size} />
            ))}
          </ul>
        ) : (
          <p className="task-empty">
            <Download size={16} />
            还没有下载任务。打开一部 DLsite 作品，点“下载”。
          </p>
        )}
        {clearable && (
          <Button variant="ghost" size="sm" onClick={() => void actions.clear()}>
            清除已取消和失败的任务
          </Button>
        )}
      </div>
    </Dialog>
  );
}
