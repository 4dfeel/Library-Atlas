import { useState, type FormEvent } from 'react';
import {
  CircleAlert,
  FolderOpen,
  FolderSearch,
  LoaderCircle,
  Pencil,
  Play,
  Plus,
  Star,
  Trash2,
} from 'lucide-react';
import { useShell } from '@/app/shell-context';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import {
  useLocalCopies,
  useLocalCopyActions,
  type CopyPreview,
  type GameDetail,
  type LocalCopy,
} from '@/lib/data';

function messageOf(error: unknown) {
  return error instanceof Error ? error.message : '操作没有完成，请重试。';
}

function folderName(path: string) {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

/** Saving links a folder and nothing more. No program in it is opened to find out what it is. */
function CopyForm({
  workId,
  copy,
  needsEntry,
  onClose,
}: {
  workId: string;
  copy: LocalCopy | null;
  needsEntry: boolean;
  onClose: () => void;
}) {
  const actions = useLocalCopyActions(workId);
  const [root, setRoot] = useState(copy?.root ?? '');
  const [preview, setPreview] = useState<CopyPreview | null>(null);
  const [entry, setEntry] = useState(copy?.entry ?? '');
  const [working, setWorking] = useState(copy?.working ?? '');
  const [argumentsText, setArguments] = useState((copy?.arguments ?? []).join('\n'));
  const [label, setLabel] = useState(copy?.label ?? '');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const look = async (path: string) => {
    setError(null);
    try {
      const next = await actions.preview(path);
      setPreview(next);
      setEntry((current) => current || next.suggested || '');
    } catch (failure) {
      setPreview(null);
      setError(messageOf(failure));
    }
  };

  const choose = async () => {
    setError(null);
    setBusy(true);
    try {
      const chosen = await actions.chooseFolder();
      if (chosen) {
        setRoot(chosen);
        await look(chosen);
      }
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy(false);
    }
  };

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const body = {
      root: root.trim(),
      entry: entry || null,
      working: working.trim() || null,
      arguments: argumentsText.split('\n').filter((line) => line.trim() !== ''),
      label: label.trim() || null,
    };
    try {
      if (copy) await actions.update(copy.id, body);
      else await actions.add(body);
      onClose();
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy(false);
    }
  };

  const entries = preview?.entries ?? [];
  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onClose()}
      title={copy ? '编辑本地文件关联' : '关联本地文件'}
      description="只记录位置，不会移动、修改或运行任何文件。"
    >
      <form className="copy-form" onSubmit={(event) => void save(event)} data-testid="copy-form">
        <label htmlFor="copy-root">文件夹</label>
        <div className="folder-controls">
          <Input
            id="copy-root"
            value={root}
            spellCheck={false}
            placeholder="作品所在的文件夹"
            onChange={(event) => setRoot(event.target.value)}
            onBlur={() => {
              if (root.trim() && root.trim() !== preview?.root) void look(root.trim());
            }}
          />
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={busy}
            onClick={() => void choose()}
          >
            <FolderSearch size={14} />
            选择
          </Button>
        </div>
        {needsEntry && (
          <>
            <label htmlFor="copy-entry">主程序</label>
            {entries.length > 0 ? (
              <select
                id="copy-entry"
                value={entry}
                onChange={(event) => setEntry(event.target.value)}
              >
                <option value="">之后再选</option>
                {entries.map((item) => (
                  <option key={item.path} value={item.path}>
                    {item.path}
                    {item.likelyHelper ? '（可能是辅助程序）' : ''}
                  </option>
                ))}
              </select>
            ) : (
              <Input
                id="copy-entry"
                value={entry}
                spellCheck={false}
                placeholder="相对于文件夹的路径，如 Game.exe"
                onChange={(event) => setEntry(event.target.value)}
              />
            )}
            {preview && entries.length > 1 && !preview.suggested && (
              <p className="settings-note">有多个可能的程序，Atlas 不会替你猜，请选择一个。</p>
            )}
            <details className="copy-advanced">
              <summary>高级选项</summary>
              <label htmlFor="copy-working">工作目录（相对于文件夹，默认是主程序所在目录）</label>
              <Input
                id="copy-working"
                value={working}
                spellCheck={false}
                onChange={(event) => setWorking(event.target.value)}
              />
              <label htmlFor="copy-arguments">启动参数（每行一个，按原样传给程序）</label>
              <textarea
                id="copy-arguments"
                rows={3}
                value={argumentsText}
                spellCheck={false}
                onChange={(event) => setArguments(event.target.value)}
              />
            </details>
          </>
        )}
        <label htmlFor="copy-label">名称（可选，有多个副本时方便区分）</label>
        <Input id="copy-label" value={label} onChange={(event) => setLabel(event.target.value)} />
        {error && (
          <p className="dlsite-message" role="alert">
            <CircleAlert size={14} />
            {error}
          </p>
        )}
        <div className="dlsite-actions">
          <Button type="submit" size="sm" disabled={busy || !root.trim()}>
            {busy && <LoaderCircle size={14} className="spin" />}
            保存
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={onClose}>
            取消
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

/** What is on this computer, and what can be done with it. Only ever acts on a click. */
export function LocalCopyPanel({ game }: { game: GameDetail }) {
  const { notify } = useShell();
  const { copies, loading } = useLocalCopies(game.id);
  const actions = useLocalCopyActions(game.id);
  const [editing, setEditing] = useState<LocalCopy | 'new' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const isGame = game.kind === 'game';
  const current = copies.find((copy) => copy.isDefault) ?? copies[0];
  if (loading) return null;

  const start = async (copy: LocalCopy) => {
    setError(null);
    setStarting(true);
    try {
      const result = await actions.launch(copy.id);
      // Handing it to Windows is all Atlas can see. Whether the game loads is not known here.
      if (result.submitted) notify('已请求启动');
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      window.setTimeout(() => setStarting(false), 1500);
    }
  };

  const run = (action: () => Promise<unknown>) => {
    setError(null);
    action().catch((failure: unknown) => setError(messageOf(failure)));
  };

  return (
    <div className="local-copy" data-testid="local-copy">
      {current ? (
        <>
          {isGame && (
            <Button
              size="sm"
              disabled={current.status !== 'ok' || starting}
              data-testid="launch"
              onClick={() => void start(current)}
            >
              {starting ? <LoaderCircle size={14} className="spin" /> : <Play size={14} />}
              启动
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            disabled={current.status === 'root_missing' || current.status === 'offline'}
            onClick={() => run(() => actions.open(current.id))}
          >
            <FolderOpen size={14} />
            打开目录
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setEditing(current)}>
            <Pencil size={14} />
            编辑关联
          </Button>
          {(!isGame && current.status === 'no_entry') || current.status === 'ok' ? null : (
            <span className="download-state is-error" data-testid="copy-status">
              <CircleAlert size={14} />
              {current.message}
            </span>
          )}
          {copies.length > 1 && (
            <ul className="local-copy-list" aria-label="本地副本">
              {copies.map((copy) => (
                <li key={copy.id}>
                  <button
                    type="button"
                    aria-pressed={copy.isDefault}
                    title={copy.isDefault ? '默认副本' : '设为默认'}
                    onClick={() => run(() => actions.setDefault(copy.id))}
                  >
                    <Star size={13} fill={copy.isDefault ? 'currentColor' : 'none'} />
                    <span title={copy.root}>{copy.label ?? folderName(copy.root)}</span>
                  </button>
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={`移除关联：${copy.label ?? folderName(copy.root)}`}
                    onClick={() => run(() => actions.remove(copy.id))}
                  >
                    <Trash2 size={13} />
                  </Button>
                </li>
              ))}
            </ul>
          )}
          <Button variant="ghost" size="sm" onClick={() => setEditing('new')}>
            <Plus size={14} />
            再加一个副本
          </Button>
          {copies.length === 1 && (
            <Button
              variant="ghost"
              size="sm"
              title="只移除 Atlas 里的记录，文件夹不受影响"
              onClick={() => run(() => actions.remove(current.id))}
            >
              <Trash2 size={14} />
              取消关联
            </Button>
          )}
        </>
      ) : (
        <Button variant="ghost" size="sm" onClick={() => setEditing('new')}>
          <FolderSearch size={14} />
          手动指定文件夹
        </Button>
      )}
      {error && (
        <span className="download-state is-error" role="alert">
          <CircleAlert size={14} />
          {error}
        </span>
      )}
      {editing && (
        <CopyForm
          workId={game.id}
          copy={editing === 'new' ? null : editing}
          needsEntry={isGame}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}
