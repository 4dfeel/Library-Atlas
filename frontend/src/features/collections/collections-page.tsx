import { useState, type FormEvent } from 'react';
import { CircleAlert, FolderHeart, Pencil, Plus, Star, Trash2 } from 'lucide-react';
import { AppLink } from '@/components/app-link';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { useCollectionActions, useCollections, type WorkCollection } from '@/lib/data';

function messageOf(failure: unknown) {
  return failure instanceof Error ? failure.message : '没有完成。';
}

/** Favorites and the user's own collections. Removing one never touches its works. */
export function CollectionsPage() {
  const { collections, favorites, loading } = useCollections();
  const actions = useCollectionActions();
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<WorkCollection | null>(null);
  const [removing, setRemoving] = useState<WorkCollection | null>(null);

  const create = (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    actions
      .create(name)
      .then(() => setName(''))
      .catch((failure: unknown) => setError(messageOf(failure)));
  };

  return (
    <main className="collections-page" data-testid="collections-page">
      <h1>收藏夹</h1>
      <form className="collections-new" onSubmit={create}>
        <Input
          aria-label="新收藏名称"
          placeholder="新收藏名称"
          maxLength={60}
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        <Button size="sm" type="submit" disabled={!name.trim()}>
          <Plus size={14} />
          新收藏
        </Button>
      </form>
      {error && (
        <p className="dlsite-message" role="alert">
          <CircleAlert size={14} />
          {error}
        </p>
      )}
      <ul className="collections-list" data-testid="collections-list">
        <li>
          <AppLink to="/library?fav=1" className="collections-link">
            <Star size={17} fill="currentColor" />
            <span>收藏夹</span>
            <em>{favorites}</em>
          </AppLink>
        </li>
        {collections.map((collection) => (
          <li key={collection.id}>
            <AppLink
              to={`/library?collection=${encodeURIComponent(collection.id)}`}
              className="collections-link"
              title={collection.name}
            >
              <FolderHeart size={17} />
              <span>{collection.name}</span>
              <em>{collection.count}</em>
            </AppLink>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`重命名 ${collection.name}`}
              onClick={() => setRenaming(collection)}
            >
              <Pencil size={14} />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`删除 ${collection.name}`}
              onClick={() => setRemoving(collection)}
            >
              <Trash2 size={14} />
            </Button>
          </li>
        ))}
      </ul>
      {!loading && collections.length === 0 && (
        <p className="settings-note">
          还没有自己的收藏。在作品上点右键，选“添加至 → 新收藏”，或者在上面新建一个。
        </p>
      )}
      {renaming && (
        <RenameDialog
          collection={renaming}
          onClose={() => setRenaming(null)}
          onRename={(next) => actions.rename(renaming.id, next)}
        />
      )}
      {removing && (
        <Dialog
          open
          onOpenChange={(open) => {
            if (!open) setRemoving(null);
          }}
          title={`删除收藏：${removing.name}`}
          description="只删除这个收藏，里面的作品还在作品库里。"
        >
          <div className="dlsite-actions">
            <Button
              size="sm"
              data-testid="collection-remove-confirm"
              onClick={() => {
                void actions.remove(removing.id).finally(() => setRemoving(null));
              }}
            >
              删除收藏
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setRemoving(null)}>
              取消
            </Button>
          </div>
        </Dialog>
      )}
    </main>
  );
}

function RenameDialog({
  collection,
  onClose,
  onRename,
}: {
  collection: WorkCollection;
  onClose: () => void;
  onRename: (name: string) => Promise<unknown>;
}) {
  const [name, setName] = useState(collection.name);
  const [error, setError] = useState<string | null>(null);
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title="重命名收藏"
      description="里面的作品不变。"
    >
      <form
        className="download-plan"
        onSubmit={(event) => {
          event.preventDefault();
          onRename(name)
            .then(onClose)
            .catch((failure: unknown) => setError(messageOf(failure)));
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
            保存
          </Button>
          <Button variant="ghost" size="sm" type="button" onClick={onClose}>
            取消
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
