import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react';
import { createPortal } from 'react-dom';
import { Check, ChevronRight, Download, Play, Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { UninstallDialog } from '@/features/game-detail/uninstall-dialog';
import { useCollectionActions, useCollections, useWorkActions, type Game } from '@/lib/data';
import { navigate } from '@/lib/router';

const EDGE = 8;

type Sub = 'add' | 'manage' | null;

function canInstall(game: Game) {
  return (
    game.platform === 'dlsite' &&
    game.capabilities.download !== false &&
    !game.capabilities.officialViewerOnly
  );
}

/**
 * What a right click offers, as on Steam: the one thing to do with this work first, then where it
 * belongs, how to manage it, and its page. Nothing here acts without the click.
 */
export function WorkMenu({
  game,
  x,
  y,
  detailHref,
  onOpen,
  onFavorite,
  onClose,
  notify,
}: {
  game: Game;
  x: number;
  y: number;
  detailHref: string;
  onOpen: () => void;
  onFavorite: () => void;
  onClose: () => void;
  notify: (message: string) => void;
}) {
  const root = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ left: x, top: y, flip: false });
  const [sub, setSub] = useState<Sub>(null);
  const [naming, setNaming] = useState(false);
  const [uninstalling, setUninstalling] = useState(false);
  const { collections } = useCollections(game.id);
  const collectionActions = useCollectionActions(game.id);
  const actions = useWorkActions(game.id);
  const dialogOpen = naming || uninstalling;
  const copyId = game.copyId ?? null;

  // Kept on screen, and the submenus open to whichever side has room.
  useLayoutEffect(() => {
    const box = root.current?.getBoundingClientRect();
    if (!box) return;
    setPosition({
      left: Math.max(EDGE, Math.min(x, window.innerWidth - box.width - EDGE)),
      top: Math.max(EDGE, Math.min(y, window.innerHeight - box.height - EDGE)),
      flip: x + box.width * 2 + EDGE > window.innerWidth,
    });
  }, [x, y]);

  useEffect(() => {
    root.current?.querySelector<HTMLElement>('[role^="menuitem"]:not(:disabled)')?.focus();
  }, []);

  useEffect(() => {
    if (dialogOpen) return undefined;
    const away = (event: Event) => {
      if (!root.current?.contains(event.target as Node)) onClose();
    };
    const closed = () => onClose();
    window.addEventListener('pointerdown', away, true);
    window.addEventListener('wheel', closed, { passive: true });
    window.addEventListener('blur', closed);
    window.addEventListener('resize', closed);
    return () => {
      window.removeEventListener('pointerdown', away, true);
      window.removeEventListener('wheel', closed);
      window.removeEventListener('blur', closed);
      window.removeEventListener('resize', closed);
    };
  }, [dialogOpen, onClose]);

  const goToPage = (suffix = '') => {
    onOpen();
    onClose();
    navigate(`${detailHref}${suffix}`, { state: { fromLibrary: true } });
  };
  const perform = (work: Promise<unknown>, done?: string) => {
    onClose();
    work
      .then(() => {
        if (done) notify(done);
      })
      .catch((failure: unknown) =>
        notify(failure instanceof Error ? failure.message : '操作没有完成。'),
      );
  };

  const onKeyDown = (event: KeyboardEvent) => {
    const items = [
      ...(root.current?.querySelectorAll<HTMLElement>('[role^="menuitem"]:not(:disabled)') ?? []),
    ];
    const here = items.indexOf(document.activeElement as HTMLElement);
    const move = (to: number) => items[(to + items.length) % items.length]?.focus();
    const owner = (document.activeElement as HTMLElement | null)?.dataset.sub as Sub | undefined;
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      if (sub) {
        root.current?.querySelector<HTMLElement>(`[data-sub="${sub}"]`)?.focus();
        setSub(null);
      } else onClose();
    } else if (event.key === 'ArrowDown') {
      event.preventDefault();
      move(here + 1);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      move(here - 1);
    } else if (event.key === 'ArrowRight' && owner) {
      event.preventDefault();
      setSub(owner);
      requestAnimationFrame(() =>
        root.current?.querySelector<HTMLElement>(`[data-in="${owner}"]:not(:disabled)`)?.focus(),
      );
    } else if (event.key === 'ArrowLeft' && sub) {
      event.preventDefault();
      root.current?.querySelector<HTMLElement>(`[data-sub="${sub}"]`)?.focus();
      setSub(null);
    } else if (event.key === 'Tab') {
      onClose();
    }
  };

  const noCopyNote = copyId ? undefined : '这部作品还没有在本机找到';
  const primary = !copyId ? (
    <button
      type="button"
      role="menuitem"
      className="work-menu-primary is-install"
      data-testid="menu-install"
      disabled={!canInstall(game)}
      title={canInstall(game) ? undefined : '这部作品不能在 Atlas 内下载'}
      onClick={() => goToPage('?install=1')}
    >
      <Download size={17} />
      安装
    </button>
  ) : game.kind === 'game' ? (
    <button
      type="button"
      role="menuitem"
      className="work-menu-primary is-play"
      data-testid="menu-play"
      title={game.launchable ? undefined : '这个文件夹有多个程序，会先让你选择'}
      onClick={() =>
        game.launchable ? perform(actions.launch(copyId), '已请求启动') : goToPage('?play=1')
      }
    >
      <Play size={17} fill="currentColor" />
      开始游戏
    </button>
  ) : (
    <button
      type="button"
      role="menuitem"
      className="work-menu-primary is-play"
      data-testid="menu-open"
      onClick={() => goToPage()}
    >
      <Play size={17} fill="currentColor" />
      打开
    </button>
  );

  return createPortal(
    <>
      <div
        ref={root}
        className="work-menu"
        role="menu"
        aria-label={game.title}
        data-testid="work-menu"
        style={{ left: position.left, top: position.top }}
        data-flip={position.flip || undefined}
        onKeyDown={onKeyDown}
        onContextMenu={(event) => event.preventDefault()}
      >
        {primary}
        <button
          type="button"
          role="menuitem"
          data-testid="menu-favorite"
          onMouseEnter={() => setSub(null)}
          onClick={() => {
            onFavorite();
            onClose();
          }}
        >
          {game.favorite ? '从收藏夹移除' : '添加至收藏夹'}
        </button>
        <div className="work-menu-branch" onMouseEnter={() => setSub('add')}>
          <button
            type="button"
            role="menuitem"
            aria-haspopup="menu"
            aria-expanded={sub === 'add'}
            data-sub="add"
            data-testid="menu-add"
            onClick={() => setSub(sub === 'add' ? null : 'add')}
          >
            添加至
            <ChevronRight size={16} />
          </button>
          {sub === 'add' && (
            <div
              className="work-menu-sub"
              role="menu"
              aria-label="添加至"
              data-testid="menu-add-list"
            >
              {collections.map((collection) => (
                <button
                  key={collection.id}
                  type="button"
                  role="menuitemcheckbox"
                  aria-checked={collection.contains}
                  data-in="add"
                  title={collection.name}
                  onClick={() => void collectionActions.toggle(collection.id, !collection.contains)}
                >
                  <span>{collection.name}</span>
                  {collection.contains && <Check size={15} />}
                </button>
              ))}
              {collections.length > 0 && <hr />}
              <button
                type="button"
                role="menuitem"
                data-in="add"
                data-testid="menu-new-collection"
                onClick={() => setNaming(true)}
              >
                <Plus size={15} />
                新收藏…
              </button>
            </div>
          )}
        </div>
        <div className="work-menu-branch" onMouseEnter={() => setSub('manage')}>
          <button
            type="button"
            role="menuitem"
            aria-haspopup="menu"
            aria-expanded={sub === 'manage'}
            data-sub="manage"
            data-testid="menu-manage"
            onClick={() => setSub(sub === 'manage' ? null : 'manage')}
          >
            管理
            <ChevronRight size={16} />
          </button>
          {sub === 'manage' && (
            <div
              className="work-menu-sub"
              role="menu"
              aria-label="管理"
              data-testid="menu-manage-list"
            >
              <button
                type="button"
                role="menuitem"
                data-in="manage"
                disabled={!copyId}
                title={noCopyNote}
                onClick={() => copyId && perform(actions.shortcut(copyId), '已添加桌面快捷方式')}
              >
                添加桌面快捷方式
              </button>
              <button
                type="button"
                role="menuitem"
                data-in="manage"
                disabled={!copyId}
                title={noCopyNote}
                onClick={() => copyId && perform(actions.browse(copyId))}
              >
                浏览本地文件
              </button>
              <hr />
              <button
                type="button"
                role="menuitem"
                data-in="manage"
                data-testid="menu-uninstall"
                disabled={!copyId}
                title={noCopyNote}
                onClick={() => setUninstalling(true)}
              >
                卸载
              </button>
            </div>
          )}
        </div>
        <hr />
        <button
          type="button"
          role="menuitem"
          data-testid="menu-properties"
          onMouseEnter={() => setSub(null)}
          onClick={() => goToPage()}
        >
          属性…
        </button>
      </div>
      {naming && (
        <NewCollection onClose={onClose} onCreate={(name) => collectionActions.create(name)} />
      )}
      {uninstalling && copyId && (
        <UninstallDialog
          copyId={copyId}
          title={game.title}
          onClose={onClose}
          onDone={() => notify('已移到回收站')}
        />
      )}
    </>,
    document.body,
  );
}

function NewCollection({
  onClose,
  onCreate,
}: {
  onClose: () => void;
  onCreate: (name: string) => Promise<unknown>;
}) {
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title="新收藏"
      description="给这个收藏起个名字，这部作品会放进去。"
    >
      <form
        className="download-plan"
        onSubmit={(event) => {
          event.preventDefault();
          onCreate(name)
            .then(onClose)
            .catch((failure: unknown) =>
              setError(failure instanceof Error ? failure.message : '没有完成。'),
            );
        }}
      >
        <Input
          aria-label="收藏名称"
          autoFocus
          maxLength={60}
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        {error && (
          <p className="dlsite-message" role="alert">
            {error}
          </p>
        )}
        <div className="dlsite-actions">
          <Button size="sm" type="submit" disabled={!name.trim()}>
            创建
          </Button>
          <Button variant="ghost" size="sm" type="button" onClick={onClose}>
            取消
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
