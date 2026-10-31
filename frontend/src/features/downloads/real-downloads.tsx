import { useEffect, useRef, useState } from 'react';
import {
  CircleAlert,
  CircleCheck,
  Download,
  FileArchive,
  FolderOpen,
  FolderSearch,
  LoaderCircle,
  RotateCcw,
} from 'lucide-react';
import { useShell } from '@/app/shell-context';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import {
  isDownloadActive,
  isExtractActive,
  useDownloadActions,
  useDownloads,
  useLocalCopies,
  useExtractionActions,
  useExtractions,
  useFolderActions,
  type DownloadPlan,
  type ExtractTask,
  type FolderInfo,
  type GameDetail,
} from '@/lib/data';
import { formatBytes } from '@/lib/utils';
import { amount, extractLabels, messageOf, stateLabels } from './labels';

const UNPACKED_NOTE = '已解压不代表已安装或可以运行，Atlas 不会运行里面的任何内容。';

/** Real bytes against a real total; without a total the bar moves and claims no number. */
export function Progress({
  done,
  total,
  label,
}: {
  done: number;
  total: number | null;
  label: string;
}) {
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
        <FolderChoice
          kind="library"
          title="作品文件夹"
          folder={plan.folder}
          emptyNote="还没有选择作品文件夹。作品会按“类型 / 制作方 / 作品名”放在里面，压缩包在 Archives 里。"
          onChanged={onReplan}
        />
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
  archiveKept,
  onStart,
  onDownloadAgain,
  onTasks,
}: {
  task: ExtractTask | undefined;
  busy: boolean;
  archiveKept: boolean;
  onStart: (again: boolean) => void;
  onDownloadAgain: () => void;
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
          {task.format === 'file' ? '已放入作品文件夹' : '已解压'}
        </span>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => void unpacking.act(task.id, 'open-folder').catch(() => undefined)}
        >
          <FolderOpen size={14} />
          打开作品文件夹
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
      {(task.canRetry || task.resultMissing) &&
        (archiveKept ? (
          <Button variant="secondary" size="sm" disabled={busy} onClick={() => onStart(true)}>
            <RotateCcw size={14} />
            重新解压
          </Button>
        ) : (
          <Button variant="secondary" size="sm" disabled={busy} onClick={onDownloadAgain}>
            <Download size={14} />
            重新下载并解压
          </Button>
        ))}
    </span>
  );
}

/** The real entry on a work's page. Nothing is requested until the user presses it. */
export function RealDownloadAction({ game }: { game: GameDetail }) {
  const { openTasks } = useShell();
  const { tasks, updates } = useDownloads();
  const { tasks: extractions } = useExtractions();
  const actions = useDownloadActions();
  const unpacking = useExtractionActions();
  const { copies, refresh: refreshCopies } = useLocalCopies(game.id);
  const hasUpdate = updates.some((update) => update.workId === game.id);
  const [plan, setPlan] = useState<DownloadPlan | null>(null);
  const [wantsExtract, setWantsExtract] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const mine = tasks.filter((task) => task.workId === game.id);
  const active = mine.filter(isDownloadActive);
  const finished = mine.filter((task) => task.state === 'done' && !task.fileMissing);
  const troubled = mine.filter((task) => task.message && task.state !== 'cancelled');
  const extraction = extractions.find((task) => task.workId === game.id);

  // Unpacking finishing is what puts a work on this computer: the page shows it straight away.
  const unpackedAt = extraction?.state === 'done' ? extraction.id : null;
  useEffect(() => {
    if (unpackedAt) void refreshCopies();
  }, [refreshCopies, unpackedAt]);

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
      } else if (next.kind === 'direct' && next.folder.status === 'ok') {
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

  // Asked for from the library's menu. Taken out of the address first, so going back and forward
  // does not start it again.
  const requested = useRef(new URLSearchParams(window.location.search).has('install'));
  useEffect(() => {
    if (!requested.current) return;
    requested.current = false;
    const url = new URL(window.location.href);
    url.searchParams.delete('install');
    window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}`);
    void begin(true, true);
    // Once, on arrival.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  // On this computer already: what to do with it is the panel below. Only an update, or trouble
  // with a download, still needs saying here.
  if (copies.length > 0 && troubled.length === 0) {
    return (
      <>
        {hasUpdate && (
          <div className="hero-download" data-testid="download-action" aria-live="polite">
            <Button
              variant="secondary"
              size="sm"
              disabled={busy}
              data-testid="download-update"
              onClick={() => void begin(true, true)}
            >
              <Download size={14} />
              下载更新
            </Button>
            {error && (
              <span className="download-state is-error" role="alert">
                <CircleAlert size={14} />
                {error}
              </span>
            )}
          </div>
        )}
        {dialog}
      </>
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
          {finished.some((task) => !task.archiveRemoved) && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() =>
                void actions.act(finished[0]!.id, 'open-folder').catch(() => undefined)
              }
            >
              <FolderOpen size={14} />
              打开压缩包位置
            </Button>
          )}
          {hasUpdate ? (
            <Button
              variant="secondary"
              size="sm"
              disabled={busy}
              data-testid="download-update"
              onClick={() => void begin(true, true)}
            >
              <Download size={14} />
              下载更新
            </Button>
          ) : (
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => void begin(Boolean(extraction), true)}
            >
              <RotateCcw size={14} />
              重新下载
            </Button>
          )}
          <ExtractRow
            task={extraction}
            busy={busy}
            archiveKept={finished.some((task) => !task.archiveRemoved)}
            onStart={(again) => void unpack(again)}
            onDownloadAgain={() => void begin(true, true)}
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
