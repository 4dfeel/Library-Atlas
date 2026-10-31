import { useState } from 'react';
import { History } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { formatPlayTime } from '@/features/activity/play-time';
import { useWorkPlay, type GameDetail } from '@/lib/data';
import { formatDate } from '@/lib/utils';

function when(text: string) {
  return `${formatDate(text) ?? ''} ${new Date(text).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  })}`;
}

/** This game's sessions, one line each. Whatever had to be estimated says so. */
export function PlayRecord({ game }: { game: GameDetail }) {
  const { play } = useWorkPlay(game.id);
  const [open, setOpen] = useState(false);
  if (!play || (!play.running && play.sessions.length === 0)) return null;
  return (
    <div className="play-record" data-testid="play-record">
      {play.running && (
        <span className="download-state is-done" role="status" data-testid="play-running">
          <i className="status-dot" />
          正在运行
        </span>
      )}
      <Button variant="ghost" size="sm" data-testid="play-open" onClick={() => setOpen(true)}>
        <History size={14} />
        游玩记录 {play.sessions.length}
      </Button>
      {open && (
        <Dialog
          open
          onOpenChange={setOpen}
          title="游玩记录"
          description={`最近两周 ${formatPlayTime(play.recentSeconds)} · 累计 ${formatPlayTime(play.totalSeconds)}`}
        >
          <table className="activity-table" data-testid="play-sessions">
            <tbody>
              {play.sessions.map((item) => (
                <tr key={item.id}>
                  <td>{when(item.startedAt)}</td>
                  <td>
                    {item.running ? '正在运行' : formatPlayTime(item.seconds)}
                    {item.estimated && '（估算，Atlas 当时没在运行）'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {play.months.length > 1 && (
            <table className="activity-table" data-testid="play-months">
              <tbody>
                {play.months.map((item) => (
                  <tr key={item.month}>
                    <td>{item.month}</td>
                    <td>{formatPlayTime(item.seconds)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Dialog>
      )}
    </div>
  );
}
