import { useState } from 'react';
import {
  CircleAlert,
  CircleCheck,
  Download,
  FileArchive,
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
  isExtractActive,
  useDownloadActions,
  useDownloads,
  useExtractionActions,
  useExtractions,
  useFolderActions,
  type DemoSize,
  type DownloadPlan,
  type DownloadTask,
  type ExtractTask,
  type FolderInfo,
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

const extractLabels: Record<ExtractTask['state'], string> = {
  queued: '等待解压',
  checking: '正在核对文件',
  extracting: '解压中',
  committing: '正在完成',
  done: '已解压',
  not_needed: '不需要解压',
  failed: '解压失败',
  cancelled: '已取消解压',
  interrupted: '解压已中断',
};

const UNPACKED_NOTE = '已解压不代表已安装或可以运行，Atlas 不会运行里面的任何内容。';

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

function FolderChoice({
  kind,
  title,
  folder,
  emptyNote,
  onChanged,
}: {
  kind: FolderInfo['kind'];
  title: string;
  folder: FolderInfo;
  emptyNote: string;
  onChanged: () => void;
}) {
  const { pick } = useFolderActions(kind);
  return (
    <section data-folder-choice={kind}>
      <h3>{title}</h3>
      {folder.path ? (
        <p className="download-path" title={folder.path}>
          {folder.path}
        </p>
      ) : (
        <p className="settings-note">{emptyNote}</p>
      )}
      {folder.status === 'missing' && (
        <p className="dlsite-message" role="alert">
          <CircleAlert size={14} />
          这个文件夹现在不存在，可能是硬盘没有连接。Atlas 不会自动重建它。
        </p>
      )}
      <Button
        variant="secondary"
        size="sm"
        disabled={pick.isPending}
        onClick={() => pick.mutate(undefined, { onSuccess: onChanged })}
      >
        {pick.isPending ? <LoaderCircle size={14} className="spin" /> : <FolderSearch size={14} />}
        {folder.path ? '更改文件夹' : '选择文件夹'}
      </Button>
      {pick.error && (
        <p className="dlsite-message" role="alert">
          <CircleAlert size={14} />
          {pick.error.message}
        </p>
      )}
    </section>
  );
}

/** Asked only when a choice is really needed: parts to pick, or a folder not chosen yet. */
function PlanDialog({
  game,
  plan,
  extract,
  onClose,
  onReplan,
  onStart,
  error,
  starting,
}: {
  game: GameDetail;
  plan: DownloadPlan;
  extract: boolean;
  onClose: () => void;
  onReplan: () => void;
  onStart: (parts: number[] | null) => void;
  error: string | null;
  starting: boolean;
}) {
  const [chosen, setChosen] = useState<Set<number>>(() => new Set(plan.parts));
  const folderReady =
    plan.folder.status === 'ok' && (!extract || plan.extractFolder.status === 'ok');
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
        <FolderChoice
          kind="library"
          title="压缩包保存到"
          folder={plan.folder}
          emptyNote="还没有选择作品文件夹。文件会放在里面以作品编号命名的子文件夹中。"
          onChanged={onReplan}
        />
        {extract && (
          <FolderChoice
            kind="extract"
            title="解压到"
            folder={plan.extractFolder}
            emptyNote="还没有选择解压文件夹。每部作品会解压到里面单独的文件夹，已有文件夹不会被覆盖。"
            onChanged={onReplan}
          />
        )}
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
            {extract ? '开始下载并解压' : '开始下载'}
          </Button>
          <Button variant="ghost" size="sm" onClick={onClose}>
            取消
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

/** What became of a finished download. A failure here leaves the download standing. */
function ExtractRow({
  task,
  busy,
  onStart,
  onTasks,
}: {
  task: ExtractTask | undefined;
  busy: boolean;
  onStart: (again: boolean) => void;
  onTasks: () => void;
}) {
  const unpacking = useExtractionActions();
  if (!task)
    return (
      <Button variant="secondary" size="sm" disabled={busy} onClick={() => onStart(false)}>
        <FileArchive size={14} />
        解压
      </Button>
    );
  if (isExtractActive(task))
    return (
      <span className="download-extract" data-testid="extract-state">
        <span className="download-state">{extractLabels[task.state]}</span>
        <Progress
          done={task.bytesDone}
          total={task.state === 'extracting' ? task.bytesTotal : null}
          label={extractLabels[task.state]}
        />
        <Button variant="ghost" size="sm" onClick={onTasks}>
          查看任务
        </Button>
      </span>
    );
  if (task.state === 'done' && !task.resultMissing)
    return (
      <span className="download-extract" data-testid="extract-state">
        <span className="download-state is-done" data-testid="extract-done">
          <CircleCheck size={14} />
          已解压
        </span>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => void unpacking.act(task.id, 'open-folder').catch(() => undefined)}
        >
          <FolderOpen size={14} />
          打开解压文件夹
        </Button>
        <span className="download-note">{UNPACKED_NOTE}</span>
      </span>
    );
  if (task.state === 'not_needed')
    return (
      <span className="download-note" data-testid="extract-state">
        这个文件不是压缩包，不需要解压。
      </span>
    );
  return (
    <span className="download-extract" data-testid="extract-state">
      <span className="download-state is-error">
        <CircleAlert size={14} />
        {task.resultMissing ? '解压结果已经不在原位置。' : task.message}
      </span>
      {(task.canRetry || task.resultMissing) && (
        <Button variant="secondary" size="sm" disabled={busy} onClick={() => onStart(true)}>
          <RotateCcw size={14} />
          重新解压
        </Button>
      )}
    </span>
  );
}

/** The real entry on a work's page. Nothing is requested until the user presses it. */
export function RealDownloadAction({ game }: { game: GameDetail }) {
  const { openTasks } = useShell();
  const { tasks } = useDownloads();
  const { tasks: extractions } = useExtractions();
  const actions = useDownloadActions();
  const unpacking = useExtractionActions();
  const [plan, setPlan] = useState<DownloadPlan | null>(null);
  const [wantsExtract, setWantsExtract] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const mine = tasks.filter((task) => task.workId === game.id);
  const active = mine.filter(isDownloadActive);
  const finished = mine.filter((task) => task.state === 'done' && !task.fileMissing);
  const troubled = mine.filter((task) => task.message && task.state !== 'cancelled');
  const extraction = extractions.find((task) => task.workId === game.id);

  const unpack = async (again = false) => {
    setBusy(true);
    setError(null);
    try {
      await unpacking.start(game.id, again);
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy(false);
    }
  };

  const start = async (parts: number[] | null, again = false) => {
    setBusy(true);
    setError(null);
    try {
      await actions.create(game.id, parts, again, wantsExtract);
      setPlan(null);
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy(false);
    }
  };

  const begin = async (extract: boolean, again = false) => {
    setBusy(true);
    setError(null);
    setWantsExtract(extract);
    try {
      const next = await actions.plan(game.id);
      if (next.kind === 'serial') {
        setError('这部作品需要序列号，暂不支持在 Atlas 内下载。');
      } else if (
        next.kind === 'direct' &&
        next.folder.status === 'ok' &&
        (!extract || next.extractFolder.status === 'ok')
      ) {
        await actions.create(game.id, null, again, extract);
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
      extract={wantsExtract}
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
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => void begin(false, true)}>
            <RotateCcw size={14} />
            重新下载
          </Button>
          <ExtractRow
            task={extraction}
            busy={busy}
            onStart={(again) => void unpack(again)}
            onTasks={openTasks}
          />
          {error && (
            <span className="download-state is-error" role="alert">
              <CircleAlert size={14} />
              {error}
            </span>
          )}
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
          <Button variant="secondary" size="sm" disabled={busy} onClick={() => void begin(true)}>
            {busy ? <LoaderCircle size={14} className="spin" /> : <FileArchive size={14} />}
            下载并解压
          </Button>
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => void begin(false)}>
            <Download size={14} />
            仅下载
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

function ExtractTaskRow({ task, size }: { task: ExtractTask; size: DemoSize }) {
  const unpacking = useExtractionActions();
  const [error, setError] = useState<string | null>(null);
  const act = (action: 'cancel' | 'retry' | 'open-folder') => () => {
    setError(null);
    unpacking.act(task.id, action).catch((failure: unknown) => setError(messageOf(failure)));
  };
  const active = isExtractActive(task);
  return (
    <li className={`task-row task-${task.state}`} data-extract-task={task.id}>
      <div className="task-row-heading">
        <AppLink to={gameHref(task.workId, size)} className="task-title" title={task.title}>
          {task.title}
        </AppLink>
        <span className="task-phase" aria-live="polite">
          {task.state === 'done' ? (
            <CircleCheck size={14} />
          ) : task.state === 'failed' ? (
            <CircleAlert size={14} />
          ) : null}
          {extractLabels[task.state]}
        </span>
      </div>
      {active && (
        <Progress
          done={task.bytesDone}
          total={task.state === 'extracting' ? task.bytesTotal : null}
          label={extractLabels[task.state]}
        />
      )}
      <div className="task-meta">
        {task.filesTotal !== null && (
          <span>
            {task.filesTotal} 个文件
            {task.bytesTotal !== null && ` · ${formatBytes(task.bytesTotal)}`}
          </span>
        )}
        {task.resultMissing && <span className="save-error">解压结果已经不在原位置</span>}
        {task.cleanupFailed && (
          <span className="save-error">
            有临时文件没能删除，可以手动删除解压文件夹里以 .atlas-extract- 开头的文件夹
          </span>
        )}
        {task.message && task.state !== 'cancelled' && (
          <span className="save-error">{task.message}</span>
        )}
        {error && <span className="save-error">{error}</span>}
        <span className="task-actions">
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
          {task.state === 'done' && !task.resultMissing && (
            <Button variant="ghost" size="sm" onClick={act('open-folder')}>
              <FolderOpen size={14} />
              打开解压文件夹
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
  const { tasks: extractions } = useExtractions();
  const actions = useDownloadActions();
  const unpacking = useExtractionActions();
  const clearable =
    tasks.some((task) => task.state === 'cancelled' || task.state === 'failed') ||
    extractions.some((task) => task.state === 'cancelled' || task.state === 'failed');
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="下载与解压"
      description="都在本地服务中进行，关闭页面也不会中断。"
    >
      <div className="tasks-dialog">
        {unreachable ? (
          <p className="service-unavailable" role="alert">
            <CircleAlert size={16} />
            本地服务没有响应，暂时无法读取下载任务。
          </p>
        ) : tasks.length || extractions.length ? (
          <ul className="task-list">
            {extractions.map((task) => (
              <ExtractTaskRow key={task.id} task={task} size={size} />
            ))}
            {tasks.map((task) => (
              <TaskRow key={task.id} task={task} size={size} />
            ))}
          </ul>
        ) : (
          <p className="task-empty">
            <Download size={16} />
            还没有任务。打开一部 DLsite 作品，点“下载并解压”。
          </p>
        )}
        {clearable && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void Promise.all([actions.clear(), unpacking.clear()])}
          >
            清除已取消和失败的任务
          </Button>
        )}
      </div>
    </Dialog>
  );
}
