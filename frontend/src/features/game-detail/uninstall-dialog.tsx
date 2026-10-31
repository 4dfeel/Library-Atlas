import { useState } from 'react';
import { CircleAlert, LoaderCircle, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { useUninstall } from '@/lib/data';
import { formatBytes } from '@/lib/utils';

/**
 * Says exactly which folder goes and how much is in it before anything happens. It goes to the
 * Recycle Bin, so it can be got back; the user's notes, ratings and collections stay either way.
 */
export function UninstallDialog({
  copyId,
  title,
  onClose,
  onDone,
}: {
  copyId: string;
  title: string;
  onClose: () => void;
  onDone?: () => void;
}) {
  const { preview, error: loadError, uninstall } = useUninstall(copyId);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const problem = error ?? loadError ?? preview?.blocked ?? null;
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) onClose();
      }}
      title={`卸载 ${title}`}
      description="文件夹会被移到回收站，还可以从回收站恢复。收藏、评分和记录都会保留。"
    >
      <div className="download-plan" data-testid="uninstall-dialog">
        {preview ? (
          <>
            <p className="download-path" data-testid="uninstall-root" title={preview.root}>
              {preview.root}
            </p>
            {!preview.blocked && (
              <p className="settings-note" data-testid="uninstall-size">
                {preview.complete ? '' : '至少 '}
                {preview.files.toLocaleString('zh-CN')} 个文件 · {formatBytes(preview.sizeBytes)}
              </p>
            )}
            {!preview.blocked && (
              <p className="settings-note">
                如果存档放在这个文件夹里，也会一起移到回收站。如果文件夹太大放不进回收站，Windows
                会先询问你，请留意弹出的窗口。
              </p>
            )}
          </>
        ) : (
          !problem && <p className="settings-note">正在检查…</p>
        )}
        {problem && (
          <p className="dlsite-message" role="alert" data-testid="uninstall-problem">
            <CircleAlert size={14} />
            {problem}
          </p>
        )}
        <div className="dlsite-actions">
          <Button
            size="sm"
            data-testid="uninstall-confirm"
            disabled={!preview || Boolean(preview.blocked) || busy}
            onClick={() => {
              if (!preview) return;
              setBusy(true);
              setError(null);
              uninstall(preview.root)
                .then(() => {
                  onDone?.();
                  onClose();
                })
                .catch((failure: unknown) => {
                  setError(failure instanceof Error ? failure.message : '没有完成。');
                  setBusy(false);
                });
            }}
          >
            {busy ? <LoaderCircle size={14} className="spin" /> : <Trash2 size={14} />}
            移到回收站
          </Button>
          <Button variant="ghost" size="sm" disabled={busy} onClick={onClose}>
            取消
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
