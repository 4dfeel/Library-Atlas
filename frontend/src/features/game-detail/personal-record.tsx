import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { CircleAlert, Check, LoaderCircle, PencilLine, Star, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  noteMaxLength,
  ratingScale,
  useUpdateGame,
  useWorkspace,
  type DemoSize,
  type GameDetail,
  type GameStatus,
} from '@/lib/data';
import { statusLabels } from '@/lib/utils';
import { guardUnsavedDrafts, noteDrafts } from './note-drafts';

type Notify = (message: string, tone?: 'success' | 'error') => void;

const statusOrder: GameStatus[] = ['unplayed', 'playing', 'completed', 'paused'];

function SaveState({
  pending,
  error,
  saved,
  idle,
  savedText = '已保存',
}: {
  pending: boolean;
  error: Error | null;
  saved: boolean;
  idle?: string;
  savedText?: string;
}) {
  return (
    <p className="save-state" aria-live="polite">
      {pending ? (
        <span className="save-pending">
          <LoaderCircle size={13} className="spin" />
          正在保存…
        </span>
      ) : error ? (
        <span className="save-error" role="alert">
          <CircleAlert size={13} />
          {error.message}
        </span>
      ) : saved ? (
        <span className="save-success">
          <Check size={13} />
          {savedText}
        </span>
      ) : (
        idle && <span>{idle}</span>
      )}
    </p>
  );
}

function StatusField({ game, size, notify }: { game: GameDetail; size: DemoSize; notify: Notify }) {
  const { isDemo } = useWorkspace();
  const mutation = useUpdateGame(size, game.id);
  const name = useId();
  // Show the requested value while saving; revert to the stored value on failure.
  const shown = mutation.isPending ? (mutation.variables.status ?? game.status) : game.status;
  return (
    <fieldset className="record-field">
      <legend>进度状态</legend>
      <div className="status-segments">
        {statusOrder.map((status) => (
          <label key={status} className={`status-segment status-${status}`}>
            <input
              type="radio"
              name={name}
              value={status}
              checked={shown === status}
              onChange={() =>
                mutation.mutate(
                  { status },
                  {
                    onSuccess: () => notify(`进度状态已改为「${statusLabels[status]}」`),
                  },
                )
              }
            />
            <i className="status-dot" />
            {statusLabels[status]}
          </label>
        ))}
      </div>
      <SaveState
        pending={mutation.isPending}
        error={mutation.error}
        saved={mutation.isSuccess}
        idle="修改后会同步到作品库的状态显示与筛选。"
        savedText={isDemo ? '已保存到本机演示存储' : '已保存'}
      />
    </fieldset>
  );
}

function RatingField({ game, size, notify }: { game: GameDetail; size: DemoSize; notify: Notify }) {
  const { isDemo } = useWorkspace();
  const mutation = useUpdateGame(size, game.id);
  const name = useId();
  const shown =
    mutation.isPending && 'rating' in mutation.variables
      ? (mutation.variables.rating ?? null)
      : game.rating;
  const stars = Array.from(
    { length: ratingScale.max - ratingScale.min + 1 },
    (_, index) => ratingScale.min + index,
  );
  const save = (rating: number | null) =>
    mutation.mutate(
      { rating },
      { onSuccess: () => notify(rating === null ? '评分已清除' : `评分已设为 ${rating} 星`) },
    );
  return (
    <fieldset className="record-field">
      <legend>
        个人评分<span className="field-rule">1–5 星 · 整数{isDemo ? ' · 演示' : ''}</span>
      </legend>
      <div className="rating-row">
        <div className="rating-stars" data-rating={shown ?? 0}>
          {stars.map((value) => (
            <label key={value} className={shown !== null && value <= shown ? 'is-on' : ''}>
              <input
                type="radio"
                name={name}
                value={value}
                checked={shown === value}
                onChange={() => save(value)}
                aria-label={`${value} 星`}
              />
              <Star
                size={22}
                strokeWidth={1.5}
                fill={shown !== null && value <= shown ? 'currentColor' : 'none'}
              />
            </label>
          ))}
        </div>
        <span className="rating-value">{shown === null ? '未评分' : `${shown} / 5`}</span>
        {shown !== null && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => save(null)}
            disabled={mutation.isPending}
          >
            <X size={14} />
            清除评分
          </Button>
        )}
      </div>
      <SaveState
        pending={mutation.isPending}
        error={mutation.error}
        saved={mutation.isSuccess}
        savedText={isDemo ? '已保存到本机演示存储' : '已保存'}
      />
    </fieldset>
  );
}

function NoteField({ game, size, notify }: { game: GameDetail; size: DemoSize; notify: Notify }) {
  const { isDemo } = useWorkspace();
  const savedText = isDemo ? '已保存到本机演示存储' : '已保存';
  const mutation = useUpdateGame(size, game.id);
  const saved = game.note;
  const [editing, setEditing] = useState(() => noteDrafts.get(game.id) !== undefined);
  const [draft, setDraft] = useState(() => noteDrafts.get(game.id) ?? saved);
  const [justSaved, setJustSaved] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const editButtonRef = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef(false);
  const labelId = useId();
  const hintId = useId();
  const dirty = editing && draft.trim() !== saved;
  const tooLong = draft.trim().length > noteMaxLength;

  useEffect(() => {
    if (dirty) {
      noteDrafts.set(game.id, draft);
      guardUnsavedDrafts();
    } else noteDrafts.delete(game.id);
  }, [dirty, draft, game.id]);
  useEffect(() => {
    if (editing) textareaRef.current?.focus();
    else if (restoreFocus.current) editButtonRef.current?.focus();
    restoreFocus.current = false;
  }, [editing]);

  const startEditing = () => {
    setDraft(saved);
    setJustSaved(false);
    mutation.reset();
    setEditing(true);
  };
  const cancel = () => {
    setDraft(saved);
    mutation.reset();
    restoreFocus.current = true;
    setEditing(false);
  };
  const save = () => {
    if (tooLong || mutation.isPending) return;
    mutation.mutate(
      // Long-lived drafts must not silently overwrite a newer note from another tab.
      { note: draft, expectedVersion: game.version },
      {
        onSuccess: () => {
          noteDrafts.delete(game.id);
          restoreFocus.current = true;
          setEditing(false);
          setJustSaved(true);
          notify(`备注${savedText}`);
        },
        onError: () => notify('备注未保存，内容仍保留在编辑框中', 'error'),
      },
    );
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
      event.preventDefault();
      save();
    } else if (event.key === 'Escape' && !dirty) {
      event.preventDefault();
      cancel();
    }
  };

  return (
    <div className="record-field note-field" role="group" aria-labelledby={labelId}>
      <div className="note-heading">
        <span id={labelId} className="field-label">
          个人备注<span className="field-rule">{isDemo ? '演示 · ' : ''}仅保存在本机</span>
        </span>
        {!editing && (
          <Button
            ref={editButtonRef}
            variant="ghost"
            size="sm"
            onClick={startEditing}
            aria-label={saved ? '编辑备注' : '添加备注'}
          >
            <PencilLine size={14} />
            {saved ? '编辑' : '添加备注'}
          </Button>
        )}
      </div>
      {editing ? (
        <>
          <textarea
            ref={textareaRef}
            className="note-input"
            aria-labelledby={labelId}
            aria-describedby={hintId}
            aria-invalid={tooLong || undefined}
            value={draft}
            maxLength={noteMaxLength + 200}
            rows={5}
            placeholder="写下你对这部作品的想法、进度或计划…"
            onChange={(event) => {
              setDraft(event.target.value);
              if (mutation.isError) mutation.reset();
            }}
            onKeyDown={onKeyDown}
          />
          <div className="note-meta" id={hintId}>
            <span className={tooLong ? 'save-error' : ''}>
              {draft.trim().length.toLocaleString('zh-CN')} /{' '}
              {noteMaxLength.toLocaleString('zh-CN')}
              {tooLong && ' · 超出字数上限'}
            </span>
            <span>Ctrl + Enter 保存{dirty ? '' : ' · Esc 取消'}</span>
          </div>
          <div className="note-actions">
            <Button size="sm" onClick={save} disabled={tooLong || mutation.isPending || !dirty}>
              {mutation.isPending ? (
                <LoaderCircle size={14} className="spin" />
              ) : (
                <Check size={14} />
              )}
              保存备注
            </Button>
            <Button variant="ghost" size="sm" onClick={cancel} disabled={mutation.isPending}>
              取消
            </Button>
            {dirty && !mutation.isPending && !mutation.isError && (
              <span className="save-dirty">有未保存的修改</span>
            )}
          </div>
          <SaveState pending={mutation.isPending} error={mutation.error} saved={false} />
        </>
      ) : saved ? (
        <>
          <p className="note-text">{saved}</p>
          {justSaved && <SaveState pending={false} error={null} saved savedText={savedText} />}
        </>
      ) : (
        <p className="note-empty">还没有备注。记录进度、感想或下次想做的事。</p>
      )}
    </div>
  );
}

export function PersonalRecord({
  game,
  size,
  notify,
}: {
  game: GameDetail;
  size: DemoSize;
  notify: Notify;
}) {
  const { isDemo, isTestLibrary } = useWorkspace();
  return (
    <section className="personal-record" aria-labelledby="personal-record-title">
      <div className="panel-heading">
        <span className="eyebrow">MY RECORD</span>
        <h2 id="personal-record-title">我的记录</h2>
        {isDemo && <span className="demo-chip">DEMO</span>}
        {isTestLibrary && <span className="demo-chip">测试数据</span>}
      </div>
      <StatusField game={game} size={size} notify={notify} />
      <RatingField game={game} size={size} notify={notify} />
      <NoteField game={game} size={size} notify={notify} />
    </section>
  );
}
