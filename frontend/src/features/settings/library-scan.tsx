import { useState } from 'react';
import { CircleAlert, CircleCheck, LoaderCircle, RotateCcw, Search, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useLibraryScan, useLibraryScanItems, type ScanItem, type ScanItemState } from '@/lib/data';

const PAGE = 50;

const stateLabels: Record<ScanItemState, string> = {
  certain: '可确定',
  likely: '很可能',
  review: '需要确认',
  unmatched: '没有匹配',
  linked: '已关联',
  ignored: '已忽略',
};

function ReviewRow({ item }: { item: ScanItem }) {
  const { link, ignore } = useLibraryScan();
  const [choice, setChoice] = useState(item.candidates[0]?.workId ?? '');
  return (
    <li className="scan-item" data-scan-item={item.id}>
      <div className="scan-item-main">
        <strong title={item.title}>{item.title}</strong>
        <span title={item.path}>
          {item.kindFolder} · {item.maker} · {item.reason}
        </span>
      </div>
      {item.state !== 'linked' && item.state !== 'ignored' && (
        <div className="scan-item-actions">
          {item.candidates.length > 1 && (
            <select
              aria-label="选择对应的作品"
              value={choice}
              onChange={(event) => setChoice(event.target.value)}
            >
              {item.candidates.map((candidate) => (
                <option key={candidate.workId} value={candidate.workId}>
                  {candidate.title}
                </option>
              ))}
            </select>
          )}
          {item.candidates.length > 0 && (
            <Button variant="secondary" size="sm" onClick={() => link(item.id, choice)}>
              关联
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={() => ignore(item.id)}>
            忽略
          </Button>
        </div>
      )}
    </li>
  );
}

function Items({ state }: { state: ScanItemState }) {
  const [offset, setOffset] = useState(0);
  const { items, total } = useLibraryScanItems(state, offset, PAGE);
  if (!total) return <p className="settings-note">没有这类结果。</p>;
  return (
    <>
      <ul className="scan-items" data-testid="scan-items">
        {items.map((item) => (
          <ReviewRow key={item.id} item={item} />
        ))}
      </ul>
      {total > PAGE && (
        <div className="dlsite-actions">
          <Button
            variant="ghost"
            size="sm"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE))}
          >
            上一页
          </Button>
          <span className="settings-note">
            {offset + 1}–{Math.min(offset + PAGE, total)} / {total}
          </span>
          <Button
            variant="ghost"
            size="sm"
            disabled={offset + PAGE >= total}
            onClick={() => setOffset(offset + PAGE)}
          >
            下一页
          </Button>
        </div>
      )}
    </>
  );
}

/**
 * Finds the library on the drives and links what clearly matches, by itself: at startup, after a
 * sync, and from this button. Reads folder names only, moves and runs nothing. Anything ambiguous
 * is listed here for the user, and a link can be taken back.
 */
export function LibraryScanPanel() {
  const { status, start, cancel, importMatches, undo, error } = useLibraryScan();
  const [drives, setDrives] = useState<Set<string> | null>(null);
  const [deep, setDeep] = useState(false);
  const [root, setRoot] = useState('');
  const [tab, setTab] = useState<ScanItemState>('review');
  if (!status) return <p className="settings-note">正在读取…</p>;
  const usable = status.volumes.filter((volume) => volume.available);
  const chosen = drives ?? new Set(usable.filter((v) => v.kind === 'fixed').map((v) => v.letter));
  const running = status.job?.state === 'running';
  const counts = status.counts;
  const accept = counts.certain + counts.likely;
  return (
    <div className="library-scan" data-testid="library-scan">
      <p className="settings-note">
        Atlas 会在启动和同步后，自动查找各个盘的 DLsiteNest\Library
        并关联匹配的作品。只读取文件夹名称，不会移动、修改或运行任何文件。
      </p>
      <details className="scan-advanced">
        <summary>高级选项：指定盘或文件夹</summary>
        <div className="scan-drives" role="group" aria-label="要扫描的盘">
          {status.volumes.map((volume) => (
            <label key={volume.letter} className={volume.available ? '' : 'is-disabled'}>
              <input
                type="checkbox"
                disabled={!volume.available || running}
                checked={chosen.has(volume.letter)}
                onChange={(event) => {
                  const next = new Set(chosen);
                  if (event.target.checked) next.add(volume.letter);
                  else next.delete(volume.letter);
                  setDrives(next);
                }}
              />
              {volume.letter}:{volume.kind === 'removable' && '（移动盘）'}
              {volume.kind === 'network' && '（网络盘，不扫描）'}
            </label>
          ))}
        </div>
        <label className="scan-deep">
          <input
            type="checkbox"
            checked={deep}
            disabled={running}
            onChange={(event) => setDeep(event.target.checked)}
          />
          深入扫描：检查盘上的目录结构（较慢）。不勾选时只看常见位置。
        </label>
        <div className="folder-controls">
          <Input
            aria-label="指定文件夹"
            placeholder="也可以直接指定一个文件夹"
            value={root}
            spellCheck={false}
            disabled={running}
            onChange={(event) => setRoot(event.target.value)}
          />
        </div>
      </details>
      <div className="dlsite-actions">
        {running ? (
          <Button variant="ghost" size="sm" onClick={cancel}>
            <X size={14} />
            取消扫描
          </Button>
        ) : (
          <Button
            size="sm"
            disabled={chosen.size === 0 && !root.trim()}
            onClick={() => start([...chosen], root.trim() ? [root.trim()] : [], deep)}
          >
            <Search size={14} />
            重新扫描并关联
          </Button>
        )}
      </div>
      {running && (
        <p className="dlsite-note" role="status" data-testid="scan-running">
          <LoaderCircle size={14} className="spin" />
          正在扫描，已检查 {status.job?.folders ?? 0} 个文件夹，发现 {status.job?.found ?? 0}{' '}
          部作品…
        </p>
      )}
      {status.job?.message && !running && (
        <p className="dlsite-message" role="status" data-testid="scan-message">
          <CircleAlert size={14} />
          {status.job.message}
        </p>
      )}
      {error && (
        <p className="dlsite-message" role="alert">
          <CircleAlert size={14} />
          {error}
        </p>
      )}
      {status.roots.length > 0 && (
        <ul className="scan-roots" aria-label="已发现的作品库">
          {status.roots.map((item) => (
            <li key={item.id} title={item.path}>
              <span className="download-path">{item.path}</span>
              {!item.available && <span className="save-error">现在不可用</span>}
            </li>
          ))}
        </ul>
      )}
      {!running && status.job && (
        <>
          <div className="dlsite-actions" data-testid="scan-summary">
            <span className="dlsite-note" role="status" data-testid="scan-linked">
              <CircleCheck size={14} />
              已关联 {counts.linked} 部
              {status.job.autoLinked > 0 && `，这次自动关联 ${status.job.autoLinked} 部`}
            </span>
            {status.job.batchId && (
              <Button variant="ghost" size="sm" onClick={() => undo(status.job!.batchId!)}>
                <RotateCcw size={14} />
                撤销这次关联
              </Button>
            )}
            {accept > 0 && (
              <Button variant="secondary" size="sm" onClick={() => void importMatches(true)}>
                <CircleCheck size={14} />
                关联 {accept} 部匹配的作品
              </Button>
            )}
          </div>
          <div className="scan-tabs" role="tablist" aria-label="扫描结果">
            {(['review', 'unmatched', 'linked', 'likely', 'certain', 'ignored'] as const).map(
              (state) => (
                <button
                  key={state}
                  type="button"
                  role="tab"
                  aria-selected={tab === state}
                  onClick={() => setTab(state)}
                >
                  {stateLabels[state]} ({counts[state]})
                </button>
              ),
            )}
          </div>
          <Items key={tab} state={tab} />
        </>
      )}
    </div>
  );
}
