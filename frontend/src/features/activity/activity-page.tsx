import { useState } from 'react';
import { CircleAlert, Gamepad2, LoaderCircle } from 'lucide-react';
import { AppLink } from '@/components/app-link';
import { usePlayStats, type PlayMonth } from '@/lib/data';
import { formatDate } from '@/lib/utils';
import { formatPlayTime } from './play-time';

function monthLabel(month: string, withYear: boolean) {
  const [year, number] = month.split('-');
  return withYear ? `${year}年${Number(number)}月` : `${Number(number)}月`;
}

/** One series, one hue, and the numbers in a table beside it: a chart never holds them alone. */
function MonthlyBars({
  months,
  chosen,
  onChoose,
}: {
  months: PlayMonth[];
  chosen: string;
  onChoose: (month: string) => void;
}) {
  const ordered = [...months].reverse();
  const most = Math.max(...ordered.map((item) => item.seconds), 1);
  return (
    <div className="play-bars" role="group" aria-label="每月游玩时长" data-testid="play-bars">
      {ordered.map((item) => (
        <button
          key={item.month}
          type="button"
          className="play-bar"
          aria-pressed={item.month === chosen}
          aria-label={`${monthLabel(item.month, true)}：${formatPlayTime(item.seconds)}`}
          title={`${monthLabel(item.month, true)} · ${formatPlayTime(item.seconds)} · ${item.sessions} 次`}
          data-month={item.month}
          onClick={() => onChoose(item.month)}
        >
          <span className="play-bar-track">
            <span
              className="play-bar-fill"
              style={{ height: item.seconds ? `${Math.max((item.seconds / most) * 100, 2)}%` : 0 }}
            />
          </span>
          <span className="play-bar-label">{monthLabel(item.month, false)}</span>
        </button>
      ))}
    </div>
  );
}

/** What Atlas has seen played. Starts counting from the first game started from Atlas. */
export function ActivityPage() {
  const { stats, loading, error } = usePlayStats();
  const [picked, setPicked] = useState<string | null>(null);
  if (loading)
    return (
      <main className="activity-page" aria-busy="true" data-testid="activity-page">
        <LoaderCircle size={18} className="spin" />
      </main>
    );
  if (error || !stats)
    return (
      <main className="activity-page" data-testid="activity-page">
        <h1>游玩记录</h1>
        <p className="dlsite-message" role="alert">
          <CircleAlert size={14} />
          {error ?? '暂时读取不到。'}
        </p>
      </main>
    );
  const current = stats.months[0];
  const month = stats.months.find((item) => item.month === picked) ?? current;
  return (
    <main className="activity-page" data-testid="activity-page">
      <h1>游玩记录</h1>
      {stats.totalSeconds === 0 ? (
        <p className="activity-empty" data-testid="activity-empty">
          <Gamepad2 size={18} />
          还没有记录。从 Atlas
          启动游戏后，这里会记下每次的时长。之前玩过的时间平台没有提供，无法补上。
        </p>
      ) : (
        <>
          <dl className="activity-totals" data-testid="activity-totals">
            <div>
              <dt>累计</dt>
              <dd>{formatPlayTime(stats.totalSeconds)}</dd>
            </div>
            <div>
              <dt>最近两周</dt>
              <dd>{formatPlayTime(stats.recentSeconds)}</dd>
            </div>
            <div>
              <dt>本月</dt>
              <dd>{formatPlayTime(current?.seconds ?? 0)}</dd>
            </div>
          </dl>
          <section aria-labelledby="activity-months">
            <h2 id="activity-months">每月时长</h2>
            <MonthlyBars months={stats.months} chosen={month?.month ?? ''} onChoose={setPicked} />
          </section>
          {month && (
            <section aria-labelledby="activity-month">
              <h2 id="activity-month">
                {monthLabel(month.month, true)} · {formatPlayTime(month.seconds)} · {month.sessions}{' '}
                次
              </h2>
              {month.top.length === 0 ? (
                <p className="settings-note">这个月没有记录。</p>
              ) : (
                <table className="activity-table" data-testid="activity-month-table">
                  <tbody>
                    {month.top.map((item) => (
                      <tr key={item.workId}>
                        <td>
                          <AppLink
                            to={`/library/${encodeURIComponent(item.workId)}`}
                            title={item.title}
                          >
                            {item.title}
                          </AppLink>
                        </td>
                        <td>{formatPlayTime(item.seconds)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          )}
          <section aria-labelledby="activity-recent">
            <h2 id="activity-recent">最近游玩</h2>
            <table className="activity-table" data-testid="activity-recent">
              <tbody>
                {stats.recent.map((item) => (
                  <tr key={item.workId}>
                    <td>
                      <AppLink
                        to={`/library/${encodeURIComponent(item.workId)}`}
                        title={item.title}
                      >
                        {item.title}
                      </AppLink>
                    </td>
                    <td>{item.running ? '正在运行' : formatDate(item.lastPlayedAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}
      <p className="settings-note">
        只统计从 Atlas 启动的游戏，开着不玩也算在内。电脑睡眠的时间不算，不足 10 秒的不算。
      </p>
    </main>
  );
}
