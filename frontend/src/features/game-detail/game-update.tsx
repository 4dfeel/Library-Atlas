import { useState } from 'react';
import {
  ArchiveRestore,
  CircleAlert,
  CircleCheck,
  LoaderCircle,
  Plus,
  RefreshCw,
  Trash2,
  Undo2,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { useGameUpdate, useLocalCopies, type GameDetail, type SaveRule } from '@/lib/data';
import { formatDate } from '@/lib/utils';

const stateLabels: Record<string, string> = {
  queued: '准备更新',
  backing_up: '正在备份存档',
  downloading: '正在下载新版本',
  unpacking: '正在解压新版本',
  replacing: '正在替换文件',
  cleaning: '正在清理旧版本',
};

/** A save's place, in the words the user would use. Nothing is searched for or guessed. */
export function SaveRules({
  rules,
  setRules,
}: {
  rules: SaveRule[];
  setRules: (rules: SaveRule[]) => void;
}) {
  return (
    <ul className="save-rules">
      {rules.map((rule, index) => (
        <li key={index}>
          <select
            aria-label="存档位置类型"
            value={rule.kind}
            onChange={(event) =>
              setRules(
                rules.map((item, position) =>
                  position === index
                    ? { ...item, kind: event.target.value as SaveRule['kind'] }
                    : item,
                ),
              )
            }
          >
            <option value="inside">游戏文件夹内</option>
            <option value="outside">其他位置</option>
            <option value="registry">注册表</option>
          </select>
          <Input
            aria-label="存档路径"
            value={rule.path}
            spellCheck={false}
            placeholder={
              rule.kind === 'inside'
                ? '如 www/save 或 Save*.dat'
                : rule.kind === 'registry'
                  ? '如 HKCU\\Software\\公司名\\游戏名'
                  : '完整路径'
            }
            onChange={(event) =>
              setRules(
                rules.map((item, position) =>
                  position === index ? { ...item, path: event.target.value } : item,
                ),
              )
            }
          />
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label="移除这个位置"
            onClick={() => setRules(rules.filter((_, position) => position !== index))}
          >
            <Trash2 size={13} />
          </Button>
        </li>
      ))}
    </ul>
  );
}

/**
 * Updating a game: its saves come first, and the old version stays until the user says the new
 * one is good. Only offered where there is a linked copy to update.
 */
export function GameUpdatePanel({ game }: { game: GameDetail }) {
  const { copies } = useLocalCopies(game.id);
  const { status, saveConfig, start, confirm, rollback, retry, restore, error } = useGameUpdate(
    game.id,
  );
  const [open, setOpen] = useState(false);
  const [rules, setRules] = useState<SaveRule[] | null>(null);
  const [none, setNone] = useState<boolean | null>(null);
  const [closed, setClosed] = useState(false);
  const current = copies.find((copy) => copy.isDefault) ?? copies[0];
  if (!current || game.kind !== 'game' || !status) return null;
  const task = status.task;
  const shownRules = rules ?? status.config.rules;
  const confirmedNone = none ?? status.config.confirmedNone;
  const working = task && stateLabels[task.state];
  const answered = confirmedNone || shownRules.some((rule) => rule.path.trim() !== '');
  return (
    <div className="game-update" data-testid="game-update">
      {working ? (
        <span className="download-state" role="status" data-testid="update-working">
          <LoaderCircle size={14} className="spin" />
          {stateLabels[task.state]}
        </span>
      ) : task?.state === 'awaiting_confirmation' ? (
        <div className="game-update-confirm" data-testid="update-waiting">
          <p>
            <CircleCheck size={14} />
            新版本已就位，存档已迁入。旧版本还保留着，先启动游戏看看。
          </p>
          {task.extraCount !== null && task.extraCount > 0 && (
            <p className="settings-note" data-testid="update-extras">
              旧版本里有 {task.extraCount} 个新版本没有的文件，清理后会一起删除：
              {task.extraSample.join('、')}
              {task.extraCount > task.extraSample.length && ' 等'}
              。多数是过时的程序文件；如果里面有你自己的东西，请先取出。
            </p>
          )}
          <div className="dlsite-actions">
            <Button size="sm" onClick={() => confirm(task.id)}>
              <CircleCheck size={14} />
              没问题，清理旧版本
            </Button>
            <Button variant="ghost" size="sm" onClick={() => rollback(task.id)}>
              <Undo2 size={14} />
              恢复旧版本
            </Button>
          </div>
        </div>
      ) : (
        <>
          <Button variant="ghost" size="sm" onClick={() => setOpen(true)}>
            <RefreshCw size={14} />
            更新本体
          </Button>
          {task?.state === 'done' && (
            <span className="download-note">
              已更新{task.cleanupFailed && '，但旧版本没能删除，可以手动处理'}
            </span>
          )}
          {task?.state === 'rolled_back' && <span className="download-note">已恢复旧版本</span>}
          {task?.message && (
            <span className="download-state is-error" role="alert" data-testid="update-problem">
              <CircleAlert size={14} />
              {task.message}
            </span>
          )}
          {task?.canRetry && task.state !== 'rolled_back' && (
            <Button variant="ghost" size="sm" onClick={() => retry(task.id)}>
              重试
            </Button>
          )}
        </>
      )}
      {error && (
        <span className="download-state is-error" role="alert">
          <CircleAlert size={14} />
          {error}
        </span>
      )}
      {open && (
        <Dialog
          open
          onOpenChange={setOpen}
          title="更新本体"
          description="先备份存档并验证，再替换游戏文件。旧版本会保留到你确认新版本没问题。"
        >
          <div className="copy-form" data-testid="update-form">
            <h3>存档在哪里？</h3>
            <p className="settings-note">Atlas 不会猜存档的位置。只有这里列出的才会被保护。</p>
            <SaveRules
              rules={shownRules}
              setRules={(next) => {
                setRules(next);
                setNone(false);
              }}
            />
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setRules([...shownRules, { kind: 'inside', path: '' }]);
                setNone(false);
              }}
            >
              <Plus size={14} />
              添加存档位置
            </Button>
            <label className="scan-deep">
              <input
                type="checkbox"
                checked={confirmedNone}
                disabled={shownRules.length > 0}
                onChange={(event) => setNone(event.target.checked)}
              />
              这部作品没有需要保留的存档
            </label>
            <label className="scan-deep">
              <input
                type="checkbox"
                checked={closed}
                onChange={(event) => setClosed(event.target.checked)}
              />
              游戏已经关闭
            </label>
            <div className="dlsite-actions">
              <Button
                size="sm"
                disabled={!answered || !closed}
                onClick={() => {
                  const cleaned = shownRules.filter((rule) => rule.path.trim() !== '');
                  void saveConfig(cleaned, confirmedNone)
                    .then(() => start(current.id))
                    .then(() => setOpen(false))
                    .catch(() => undefined);
                }}
              >
                开始更新
              </Button>
            </div>
            {status.backups.length > 0 && (
              <>
                <h3>存档备份</h3>
                <ul className="save-backups" data-testid="save-backups">
                  {status.backups.map((backup) => (
                    <li key={backup.id}>
                      <span>
                        {formatDate(backup.createdAt)} · {backup.files} 个文件
                      </span>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={!backup.available}
                        title="恢复前会先备份现在的存档"
                        onClick={() => restore(backup.id, current.id)}
                      >
                        <ArchiveRestore size={13} />
                        恢复
                      </Button>
                    </li>
                  ))}
                </ul>
              </>
            )}
            {error && (
              <p className="dlsite-message" role="alert">
                <CircleAlert size={14} />
                {error}
              </p>
            )}
          </div>
        </Dialog>
      )}
    </div>
  );
}
