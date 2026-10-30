import { CircleAlert, CircleCheck, Download, RotateCcw, X } from 'lucide-react';
import { AppLink } from '@/components/app-link';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import {
  demoTasks,
  isActiveTask,
  useDemoTasks,
  type DemoSize,
  type DemoTask,
  type TaskPhase,
} from '@/lib/data';
import { gameHref } from '@/lib/router';
import { formatBytes } from '@/lib/utils';
import { phaseLabels, taskSummary } from './labels';

/** Determinate bar with a percentage, or an indeterminate bar without fake numbers. */
export function TaskProgress({ task }: { task: DemoTask }) {
  if (!isActiveTask(task)) return null;
  const determinate = task.progress !== null;
  const percent = determinate ? Math.round(task.progress! * 100) : null;
  return (
    <div
      className={`task-progress${determinate ? '' : ' is-indeterminate'}`}
      role="progressbar"
      aria-label={`${phaseLabels[task.phase]}进度`}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent ?? undefined}
      aria-valuetext={percent === null ? `${phaseLabels[task.phase]}，进度未知` : `${percent}%`}
    >
      <span style={determinate ? { width: `${percent}%` } : undefined} />
    </div>
  );
}

function TaskRow({ task, size }: { task: DemoTask; size: DemoSize }) {
  const steps: TaskPhase[] = task.needsExtract
    ? ['downloading', 'verifying', 'extracting']
    : ['downloading', 'verifying'];
  return (
    <li className={`task-row task-${task.phase}`} data-task={task.workId}>
      <div className="task-row-heading">
        <AppLink to={gameHref(task.workId, size)} className="task-title" title={task.title}>
          {task.title}
        </AppLink>
        <span className="task-phase" aria-live="polite">
          {task.phase === 'done' ? (
            <CircleCheck size={14} />
          ) : task.phase === 'failed' ? (
            <CircleAlert size={14} />
          ) : null}
          {taskSummary(task)}
        </span>
      </div>
      <ol className="task-steps" aria-label="步骤">
        {steps.map((step) => {
          const order = ['queued', ...steps, 'done'];
          const reached = task.phase === 'done' || order.indexOf(task.phase) > order.indexOf(step);
          return (
            <li
              key={step}
              className={task.phase === step ? 'is-current' : reached ? 'is-done' : ''}
            >
              {phaseLabels[step]}
            </li>
          );
        })}
        {!task.needsExtract && <li className="is-skipped">无需解压</li>}
      </ol>
      <TaskProgress task={task} />
      <div className="task-meta">
        <span>{task.sizeBytes === null ? '大小未知' : formatBytes(task.sizeBytes)}</span>
        {task.error && <span className="save-error">{task.error}</span>}
        {task.phase === 'done' && <span>演示完成 · 未写入任何文件</span>}
        <span className="task-actions">
          {isActiveTask(task) && (
            <Button variant="ghost" size="sm" onClick={() => demoTasks.cancel(task.workId)}>
              <X size={14} />
              取消
            </Button>
          )}
          {(task.phase === 'failed' || task.phase === 'cancelled') && (
            <Button variant="secondary" size="sm" onClick={() => demoTasks.retry(task.workId)}>
              <RotateCcw size={14} />
              重试
            </Button>
          )}
        </span>
      </div>
    </li>
  );
}

export function TasksDialog({
  open,
  onOpenChange,
  size,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  size: DemoSize;
}) {
  const tasks = useDemoTasks();
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="下载与解压（演示）"
      description="仅演示流程：不会下载、校验或解压任何真实文件，也不会写入磁盘。刷新页面会丢弃未完成的演示任务。"
    >
      <div className="tasks-dialog">
        {tasks.length ? (
          <ul className="task-list">
            {tasks.map((task) => (
              <TaskRow key={task.workId} task={task} size={size} />
            ))}
          </ul>
        ) : (
          <p className="task-empty">
            <Download size={16} />
            暂无演示任务。打开支持下载的 DLsite 作品详情，可以试试“演示下载并解压”。
          </p>
        )}
        {tasks.some((task) => !isActiveTask(task)) && (
          <Button variant="ghost" size="sm" onClick={() => demoTasks.clearFinished()}>
            清除已结束的任务
          </Button>
        )}
      </div>
    </Dialog>
  );
}
