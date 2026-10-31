import { useState } from 'react';
import { CircleAlert, LoaderCircle, Search, Timer } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useSaveSuggestions, type SaveRule, type SaveSuggestion } from '@/lib/data';
import { formatBytes, formatDate } from '@/lib/utils';

const kindLabels: Record<SaveRule['kind'], string> = {
  inside: '游戏文件夹内',
  outside: '其他位置',
  registry: '注册表',
};

function Row({
  item,
  chosen,
  onToggle,
}: {
  item: SaveSuggestion;
  chosen: boolean;
  onToggle: (item: SaveSuggestion, chosen: boolean) => void;
}) {
  const when = item.modifiedAt ? formatDate(item.modifiedAt) : null;
  return (
    <li>
      <label>
        <input
          type="checkbox"
          checked={chosen}
          aria-label={`使用这个位置：${item.path}`}
          onChange={(event) => onToggle(item, event.target.checked)}
        />
        <span className="save-finder-path" title={item.path}>
          {kindLabels[item.kind]} · {item.path}
        </span>
      </label>
      <span className="settings-note">
        {item.reason} · {item.kind === 'registry' ? `${item.files} 项` : `${item.files} 个文件`}
        {item.kind !== 'registry' && ` · ${formatBytes(item.sizeBytes)}`}
        {when && ` · 最后修改 ${when}`}
      </span>
      {item.samples.length > 0 && (
        <span className="settings-note save-finder-samples" title={item.samples.join('、')}>
          {item.samples.join('、')}
        </span>
      )}
    </li>
  );
}

/**
 * Where a game's saves might be, for the user to tick. Nothing is used until they do, because a
 * confident wrong answer would look like a backup and not be one.
 */
export function SaveFinder({
  workId,
  rules,
  onChange,
}: {
  workId: string;
  rules: SaveRule[];
  onChange: (rules: SaveRule[]) => void;
}) {
  const { data, actions, error } = useSaveSuggestions(workId);
  const [showOthers, setShowOthers] = useState(false);
  if (!data) return <p className="settings-note">正在查看游戏文件…</p>;
  const session = data.session.state;
  const has = (item: SaveSuggestion) =>
    rules.some(
      (rule) => rule.kind === item.kind && rule.path.toLowerCase() === item.path.toLowerCase(),
    );
  const toggle = (item: SaveSuggestion, chosen: boolean) =>
    onChange(
      chosen
        ? [...rules.filter((rule) => rule.path.trim()), { kind: item.kind, path: item.path }]
        : rules.filter(
            (rule) =>
              !(rule.kind === item.kind && rule.path.toLowerCase() === item.path.toLowerCase()),
          ),
    );
  const likely = data.suggestions.filter((item) => item.likely);
  const others = data.suggestions.filter((item) => !item.likely);
  return (
    <div className="save-finder" data-testid="save-finder">
      <p className="settings-note" data-testid="save-engine">
        {data.engine ? `看起来是 ${data.engine} 游戏。` : '没有认出这个游戏的引擎。'}
        下面是找到的位置，勾选你确认的。
      </p>
      {likely.length > 0 && (
        <ul className="save-finder-list" data-testid="save-likely">
          {likely.map((item) => (
            <Row key={item.kind + item.path} item={item} chosen={has(item)} onToggle={toggle} />
          ))}
        </ul>
      )}
      {likely.length === 0 && session !== 'scanning' && (
        <p className="settings-note" data-testid="save-none">
          {session === 'done'
            ? '这次没有发现明显是存档的文件。可以再玩一次并确认存过档，或者查一下这部游戏的说明。'
            : '还没有找到。玩一次并存一次档，Atlas 就能看出它写到了哪里。'}
        </p>
      )}
      {others.length > 0 && (
        <>
          <Button
            variant="ghost"
            size="sm"
            aria-expanded={showOthers}
            data-testid="save-others-toggle"
            onClick={() => setShowOthers(!showOthers)}
          >
            这段时间其他有变化的位置（{others.length}），多半不是存档
          </Button>
          {showOthers && (
            <ul className="save-finder-list" data-testid="save-others">
              {others.map((item) => (
                <Row key={item.kind + item.path} item={item} chosen={has(item)} onToggle={toggle} />
              ))}
            </ul>
          )}
        </>
      )}
      <div className="dlsite-actions">
        {session === 'scanning' ? (
          <span className="dlsite-note" role="status" data-testid="save-scanning">
            <LoaderCircle size={14} className="spin" />
            正在查找这段时间有变化的文件…
          </span>
        ) : session === 'recording' ? (
          <>
            <span className="dlsite-note" role="status" data-testid="save-recording">
              <Timer size={14} />
              正在记录：去玩一会儿，存一次档，然后关闭游戏
            </span>
            <Button
              size="sm"
              variant="secondary"
              data-testid="save-finish"
              onClick={() => void actions.finish()}
            >
              <Search size={14} />
              我玩完了，查找存档
            </Button>
          </>
        ) : (
          <Button
            size="sm"
            variant="ghost"
            data-testid="save-start"
            onClick={() => void actions.start()}
          >
            <Timer size={14} />
            {session === 'done' ? '再记录一次' : '开始记录，然后去玩'}
          </Button>
        )}
      </div>
      <p className="settings-note">
        只看文件名、时间和大小，不打开文件内容，也不会上传。其他程序同时写入的文件也可能混进来，所以由你确认。
        {!data.session.complete && ' 这次检查的文件太多，没有查完。'}
      </p>
      {error && (
        <p className="dlsite-message" role="alert">
          <CircleAlert size={14} />
          {error}
        </p>
      )}
    </div>
  );
}
