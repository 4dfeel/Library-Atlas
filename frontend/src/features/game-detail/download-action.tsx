import {
  BookLock,
  CircleAlert,
  CircleCheck,
  Download,
  ListChecks,
  RotateCcw,
  X,
} from 'lucide-react';
import { useShell } from '@/app/shell-context';
import { Button } from '@/components/ui/button';
import { TaskProgress } from '@/features/demo-services/tasks-dialog';
import { taskSummary } from '@/features/demo-services/labels';
import {
  demoTasks,
  isActiveTask,
  startDemoDownload,
  useDemoTasks,
  type DemoSize,
  type GameDetail,
} from '@/lib/data';
import { formatBytes } from '@/lib/utils';

/**
 * Demo download-and-extract entry. Shown only where the work's capabilities allow
 * it; Steam installs and official-viewer-only works get no download button.
 */
export function DownloadAction({ game, size }: { game: GameDetail; size: DemoSize }) {
  const task = useDemoTasks().find((entry) => entry.workId === game.id);
  const { openTasks } = useShell();
  if (game.capabilities.officialViewerOnly)
    return (
      <p className="hero-download is-note" data-testid="download-action">
        <BookLock size={14} />
        仅限 DLsite 官方阅读器查看 · Atlas 不提供下载，也不绕过授权
      </p>
    );
  if (!game.capabilities.download) return null;
  const size_ = game.file?.sizeBytes;
  const sizeText = size_ === null || size_ === undefined ? '大小未知' : formatBytes(size_);
  const label = game.capabilities.extract ? '演示下载并解压' : '演示下载';

  return (
    <div className="hero-download" data-testid="download-action" aria-live="polite">
      {task && isActiveTask(task) ? (
        <>
          <span className="download-state">{taskSummary(task)}</span>
          <TaskProgress task={task} />
          <Button variant="ghost" size="sm" onClick={() => demoTasks.cancel(game.id)}>
            <X size={14} />
            取消
          </Button>
          <Button variant="ghost" size="sm" onClick={openTasks}>
            <ListChecks size={14} />
            查看任务
          </Button>
        </>
      ) : game.installed ? (
        <span className="download-state is-done">
          <CircleCheck size={14} />
          已下载（演示）· {game.capabilities.extract ? '已解压，' : ''}未写入任何真实文件
        </span>
      ) : task?.phase === 'failed' ? (
        <>
          <span className="download-state is-error">
            <CircleAlert size={14} />
            {task.error}
          </span>
          <Button variant="secondary" size="sm" onClick={() => demoTasks.retry(game.id)}>
            <RotateCcw size={14} />
            重试
          </Button>
        </>
      ) : (
        <>
          <Button variant="secondary" size="sm" onClick={() => startDemoDownload(game, size)}>
            <Download size={14} />
            {label}
          </Button>
          <span className="download-note">
            {task?.phase === 'cancelled' ? '已取消 · ' : ''}
            {sizeText} · 仅演示，不会下载或写入实际文件
          </span>
        </>
      )}
    </div>
  );
}
