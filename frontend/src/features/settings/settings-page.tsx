import { useEffect, useState, type FormEvent } from 'react';
import { CircleAlert, FolderOpen, FolderSearch, LoaderCircle } from 'lucide-react';
import { useShell } from '@/app/shell-context';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { DlsiteConnectionPanel } from '@/features/workspace/dlsite-connection';
import { WorkspaceSwitch } from '@/features/workspace/workspace-switch';
import { LibraryScanPanel } from './library-scan';
import { useFolderActions, useFolders, useWorkspace, type FolderInfo } from '@/lib/data';

const folderText: Record<FolderInfo['kind'], { title: string; note: string }> = {
  library: {
    title: '作品文件夹',
    note: '作品解压后放在这里，按“类型 / 制作方 / 作品名”分类。已有文件夹不会被覆盖。',
  },
  download_cache: {
    title: '压缩包文件夹',
    note: '下载的压缩包保存在这里。不单独选择时，放在作品文件夹的 Archives 里。',
  },
};

function FolderRow({ folder }: { folder: FolderInfo }) {
  const { notify } = useShell();
  const { pick, open, save } = useFolderActions(folder.kind);
  const text = folderText[folder.kind];
  const [draft, setDraft] = useState(folder.path ?? '');
  // A new saved path replaces whatever was being typed.
  const [savedPath, setSavedPath] = useState(folder.path);
  if (savedPath !== folder.path) {
    setSavedPath(folder.path);
    setDraft(folder.path ?? '');
  }
  const dirty = draft.trim() !== (folder.path ?? '') && draft.trim() !== '';
  const error = pick.error ?? open.error ?? save.error;
  const busy = pick.isPending || open.isPending || save.isPending;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (dirty) save.mutate(draft, { onSuccess: () => notify(`${text.title}已更新`) });
  };

  return (
    <form className="folder-row" onSubmit={submit} data-folder={folder.kind}>
      <label htmlFor={`folder-${folder.kind}`}>{text.title}</label>
      <p className="settings-note">{text.note}</p>
      <div className="folder-controls">
        <Input
          id={`folder-${folder.kind}`}
          value={draft}
          placeholder="还没有选择，下载前需要设置"
          spellCheck={false}
          onChange={(event) => {
            setDraft(event.target.value);
            save.reset();
          }}
        />
        {dirty ? (
          <Button type="submit" variant="secondary" size="sm" disabled={busy}>
            保存
          </Button>
        ) : (
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={busy}
            onClick={() => pick.mutate()}
          >
            {pick.isPending ? (
              <LoaderCircle size={14} className="spin" />
            ) : (
              <FolderSearch size={14} />
            )}
            更改
          </Button>
        )}
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={busy || folder.status !== 'ok'}
          onClick={() => open.mutate()}
        >
          <FolderOpen size={14} />
          打开
        </Button>
      </div>
      {pick.isPending && <p className="settings-note">请在弹出的窗口里选择文件夹。</p>}
      {folder.status === 'missing' && (
        <p className="dlsite-message" role="alert">
          <CircleAlert size={14} />
          这个文件夹现在不存在，可能是硬盘没有连接。Atlas 不会自动重建它。
        </p>
      )}
      {folder.isDefault && folder.status === 'ok' && (
        <p className="settings-note">当前使用默认位置，需要时才会创建。</p>
      )}
      {error && (
        <p className="dlsite-message" role="alert">
          <CircleAlert size={14} />
          {error.message}
        </p>
      )}
    </form>
  );
}

function Folders() {
  const query = useFolders();
  if (query.isPending) return <p className="settings-note">正在读取…</p>;
  if (!query.data)
    return (
      <p className="dlsite-message" role="alert">
        <CircleAlert size={14} />
        本地服务没有响应，暂时无法读取文件夹设置。
      </p>
    );
  return (
    <>
      {query.data.map((folder) => (
        <FolderRow key={folder.kind} folder={folder} />
      ))}
    </>
  );
}

export function SettingsPage({ onDemoSettings }: { onDemoSettings: () => void }) {
  const { isDemo, isTestLibrary } = useWorkspace();
  useEffect(() => {
    document.title = '设置 · Library Atlas';
  }, []);
  return (
    <main className="detail-page settings-page" data-testid="settings-page">
      <div className="detail-frame settings-frame">
        <header>
          <span className="eyebrow">SETTINGS</span>
          <h1>设置</h1>
        </header>

        <section className="settings-section" aria-labelledby="settings-account">
          <h2 id="settings-account">账号</h2>
          {isDemo ? (
            <p className="settings-note">
              演示空间不连接真实账号。切换到“我的资料库”后可以登录 DLsite。
            </p>
          ) : (
            <>
              <div className="settings-account" data-source="dlsite">
                <h3>DLsite</h3>
                <DlsiteConnectionPanel />
              </div>
              <div className="settings-account">
                <h3>Steam</h3>
                <p className="settings-note">连接将在后续版本开放。</p>
              </div>
            </>
          )}
        </section>

        <section className="settings-section" aria-labelledby="settings-folders">
          <h2 id="settings-folders">文件夹</h2>
          {isDemo ? (
            <p className="settings-note">演示下载不会写入任何文件，所以这里没有文件夹设置。</p>
          ) : (
            <>
              <p className="settings-note">
                更改文件夹只影响之后的下载，已有任务和文件不会被移动。
              </p>
              <Folders />
            </>
          )}
        </section>

        {!isDemo && (
          <section className="settings-section" aria-labelledby="settings-scan">
            <h2 id="settings-scan">本机作品库</h2>
            <LibraryScanPanel />
          </section>
        )}

        <section className="settings-section" aria-labelledby="settings-space">
          <h2 id="settings-space">资料空间</h2>
          <WorkspaceSwitch />
          {isTestLibrary && <p className="settings-note">当前是隔离测试库，内容都是合成样本。</p>}
          {isDemo && (
            <Button variant="ghost" size="sm" onClick={onDemoSettings}>
              演示规模与重置…
            </Button>
          )}
        </section>
      </div>
    </main>
  );
}
