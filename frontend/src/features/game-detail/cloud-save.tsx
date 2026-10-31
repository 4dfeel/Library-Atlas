import { useState } from 'react';
import {
  CircleAlert,
  CircleCheck,
  Cloud,
  CloudDownload,
  CloudOff,
  CloudUpload,
  History,
  LoaderCircle,
  RotateCcw,
  Settings2,
  TriangleAlert,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import {
  useGameUpdate,
  useLocalCopies,
  useWorkCloud,
  type CloudSnapshot,
  type GameDetail,
  type SaveRule,
} from '@/lib/data';
import { formatBytes, formatDate } from '@/lib/utils';
import { SaveRules } from './game-update';
import { SaveFinder } from './save-finder';

/** "Done" is said only of what Drive has and can give back. A queued one says it is queued. */
const stateText: Record<string, string> = {
  not_connected: '云存档：未连接',
  unconfigured: '云存档：还没设置存档位置',
  no_saves: '云存档：这部游戏没有存档',
  no_copy: '云存档：没有本地文件',
  folder_offline: '云存档：游戏文件夹现在不可用',
  empty: '云存档：还没有存档',
  local_only: '云存档：只在本机，还没有上传',
  local_changed: '云存档：本机有新进度，还没有上传',
  pending: '云存档：快照已生成，等待上传',
  uploading: '云存档：正在上传',
  synced: '云存档：已同步，云端可恢复',
  cloud_update: '云存档：云端有更新',
  conflict: '云存档：两边都有不同的进度',
  needs_auth: '云存档：需要重新授权',
  offline: '云存档：连不上 Google Drive',
  quota: '云存档：Google Drive 空间不足',
  error: '云存档：出了问题',
  restore_interrupted: '云存档：上次恢复没有完成',
  too_large: '云存档：存档太大',
  changing: '云存档：存档正在变化',
};

function StateIcon({ state }: { state: string }) {
  if (state === 'synced') return <CircleCheck size={14} />;
  if (state === 'uploading' || state === 'pending')
    return <LoaderCircle size={14} className="spin" />;
  if (state === 'cloud_update') return <CloudDownload size={14} />;
  if (state === 'conflict' || state === 'restore_interrupted') return <TriangleAlert size={14} />;
  if (state === 'offline' || state === 'not_connected') return <CloudOff size={14} />;
  if (state === 'needs_auth' || state === 'quota' || state === 'error')
    return <CircleAlert size={14} />;
  return <Cloud size={14} />;
}

function describe(item: CloudSnapshot) {
  const when = formatDate(item.createdAt) ?? '时间未知';
  const time = item.createdAt ? new Date(item.createdAt).toLocaleTimeString('zh-CN') : '';
  return `${item.thisDevice ? '这台电脑' : item.deviceName} · ${when} ${time} · ${item.files} 个文件 · ${formatBytes(item.sizeBytes)}`;
}

/** Restoring asks the same thing wherever it starts: which one, and is the game really closed. */
function RestoreDialog({
  title,
  description,
  choices,
  allowKeepLocal,
  onChoose,
  onClose,
}: {
  title: string;
  description: string;
  choices: CloudSnapshot[];
  allowKeepLocal: boolean;
  onChoose: (keep: string) => Promise<unknown>;
  onClose: () => void;
}) {
  const [closed, setClosed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const choose = (keep: string) => {
    setBusy(true);
    setError(null);
    onChoose(keep)
      .then(onClose)
      .catch((failure: unknown) => {
        setError(failure instanceof Error ? failure.message : '没有完成。');
        setBusy(false);
      });
  };
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) onClose();
      }}
      title={title}
      description={description}
    >
      <div className="download-plan" data-testid="cloud-restore">
        <ul className="cloud-history">
          {choices.map((item) => (
            <li key={item.id}>
              <span>{describe(item)}</span>
              <Button
                size="sm"
                variant="secondary"
                disabled={!closed || busy || !item.restorable}
                title={item.restorable ? undefined : '这份快照和这里的存档设置不一致，不能恢复'}
                data-testid="cloud-use"
                onClick={() => choose(item.id)}
              >
                {item.restorable ? '用这一份' : '不能恢复'}
              </Button>
            </li>
          ))}
          {allowKeepLocal && (
            <li>
              <span>这台电脑上现在的存档</span>
              <Button
                size="sm"
                variant="secondary"
                disabled={busy}
                data-testid="cloud-keep-local"
                onClick={() => choose('local')}
              >
                保留并上传
              </Button>
            </li>
          )}
        </ul>
        <label className="scan-deep">
          <input
            type="checkbox"
            checked={closed}
            data-testid="cloud-closed"
            onChange={(event) => setClosed(event.target.checked)}
          />
          游戏已经关闭
        </label>
        <p className="settings-note">
          恢复前会先备份这台电脑现有的存档。校验只能证明文件完好，不能保证新旧版本的游戏互相兼容。
        </p>
        {error && (
          <p className="dlsite-message" role="alert">
            <CircleAlert size={14} />
            {error}
          </p>
        )}
      </div>
    </Dialog>
  );
}

function ConfigDialog({
  workId,
  rules,
  none,
  onSave,
  onClose,
}: {
  workId: string;
  rules: SaveRule[];
  none: boolean;
  onSave: (rules: SaveRule[], none: boolean) => Promise<unknown>;
  onClose: () => void;
}) {
  const [shown, setShown] = useState<SaveRule[]>(
    rules.length ? rules : [{ kind: 'inside', path: '' }],
  );
  const [error, setError] = useState<string | null>(null);
  const [confirmedNone, setConfirmedNone] = useState(none);
  const cleaned = shown.filter((rule) => rule.path.trim());
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title="存档位置"
      description="只备份你在这里确认的位置，不会上传游戏本体。"
    >
      <div className="download-plan" data-testid="cloud-config">
        {!confirmedNone && <SaveFinder workId={workId} rules={shown} onChange={setShown} />}
        {!confirmedNone && <h3 className="save-finder-heading">已确认的位置</h3>}
        {!confirmedNone && <SaveRules rules={shown} setRules={setShown} />}
        {!confirmedNone && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShown([...shown, { kind: 'inside', path: '' }])}
          >
            再加一个位置
          </Button>
        )}
        <label className="scan-deep">
          <input
            type="checkbox"
            checked={confirmedNone}
            onChange={(event) => setConfirmedNone(event.target.checked)}
          />
          这部游戏没有存档
        </label>
        {error && (
          <p className="dlsite-message" role="alert">
            <CircleAlert size={14} />
            {error}
          </p>
        )}
        <div className="dlsite-actions">
          <Button
            size="sm"
            data-testid="cloud-config-save"
            disabled={!confirmedNone && cleaned.length === 0}
            onClick={() => {
              setError(null);
              onSave(confirmedNone ? [] : cleaned, confirmedNone)
                .then(onClose)
                .catch((failure: unknown) =>
                  setError(failure instanceof Error ? failure.message : '没有保存。'),
                );
            }}
          >
            保存
          </Button>
          <Button variant="ghost" size="sm" onClick={onClose}>
            取消
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

/** A linked game's saves in the user's own Google Drive. Nothing is overwritten without asking. */
export function CloudSavePanel({ game }: { game: GameDetail }) {
  const { copies } = useLocalCopies(game.id);
  const { cloud, actions, error } = useWorkCloud(game.id);
  const { status: update, saveConfig } = useGameUpdate(game.id);
  const [dialog, setDialog] = useState<'restore' | 'conflict' | 'history' | 'config' | null>(null);
  if (game.kind !== 'game' || copies.length === 0 || !cloud) return null;
  const state = cloud.state;
  const heads = cloud.history.filter((item) => item.isHead);
  const canUpload = state === 'local_only' || state === 'local_changed' || state === 'synced';
  return (
    <div className="cloud-save" data-testid="cloud-save" data-state={state}>
      <span
        className={`download-state${state === 'synced' ? ' is-done' : ''}`}
        role="status"
        data-testid="cloud-state"
      >
        <StateIcon state={state} />
        {stateText[state] ?? '云存档'}
        {cloud.queue.count > 1 && ` · ${cloud.queue.count} 份`}
      </span>
      {(state === 'unconfigured' || state === 'no_saves') && (
        <Button
          variant="ghost"
          size="sm"
          data-testid="cloud-configure"
          onClick={() => setDialog('config')}
        >
          <Settings2 size={14} />
          设置存档位置
        </Button>
      )}
      {state !== 'unconfigured' && state !== 'no_saves' && update && (
        <Button
          variant="ghost"
          size="sm"
          data-testid="cloud-configure-again"
          onClick={() => setDialog('config')}
        >
          <Settings2 size={14} />
          存档位置
        </Button>
      )}
      {canUpload && state !== 'synced' && (
        <Button
          variant="secondary"
          size="sm"
          data-testid="cloud-backup"
          onClick={() => void actions.backup().catch(() => undefined)}
        >
          <CloudUpload size={14} />
          备份到云端
        </Button>
      )}
      {(state === 'cloud_update' || state === 'restore_interrupted') && (
        <Button
          variant="secondary"
          size="sm"
          data-testid="cloud-restore-open"
          onClick={() => setDialog('restore')}
        >
          <CloudDownload size={14} />
          {state === 'cloud_update' ? '恢复云端存档' : '重新恢复'}
        </Button>
      )}
      {state === 'conflict' && (
        <Button
          variant="secondary"
          size="sm"
          data-testid="cloud-conflict-open"
          onClick={() => setDialog('conflict')}
        >
          <TriangleAlert size={14} />
          选择保留哪一份
        </Button>
      )}
      {(state === 'quota' || state === 'error') && cloud.queue.count > 0 && (
        <Button variant="ghost" size="sm" onClick={() => void actions.retry()}>
          <RotateCcw size={14} />
          重试上传
        </Button>
      )}
      {cloud.history.length > 0 && (
        <Button
          variant="ghost"
          size="sm"
          data-testid="cloud-history-open"
          onClick={() => setDialog('history')}
        >
          <History size={14} />
          历史 {cloud.history.length}
        </Button>
      )}
      {cloud.message && state !== 'not_connected' && (
        <span className="settings-note" data-testid="cloud-message">
          {cloud.message}
        </span>
      )}
      {state === 'not_connected' && (
        <span className="settings-note">在“设置 → 云存档”连接 Google Drive 后可用。</span>
      )}
      {error && (
        <span className="download-state is-error" role="alert" data-testid="cloud-error">
          <CircleAlert size={14} />
          {error}
        </span>
      )}
      {dialog === 'config' && update && (
        <ConfigDialog
          workId={game.id}
          rules={update.config.rules}
          none={update.config.confirmedNone}
          onSave={async (rules, none) => {
            await saveConfig(rules, none);
            await actions.refresh();
          }}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog === 'restore' && (
        <RestoreDialog
          title="恢复云端存档"
          description="把这一份放回这台电脑。"
          choices={heads.length ? heads : cloud.history.slice(0, 1)}
          allowKeepLocal={false}
          onChoose={actions.restore}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog === 'history' && (
        <RestoreDialog
          title="云存档历史"
          description="每次备份都单独保留。可以恢复任意一份。"
          choices={cloud.history}
          allowKeepLocal={false}
          onChoose={actions.restore}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog === 'conflict' && (
        <RestoreDialog
          title="选择保留哪一份"
          description="两边各有不同的进度，Atlas 不替你决定，也不按时间判断。没选中的那一份仍保留在历史里。"
          choices={heads}
          allowKeepLocal
          onChoose={actions.resolve}
          onClose={() => setDialog(null)}
        />
      )}
    </div>
  );
}
