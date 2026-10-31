import { BookLock } from 'lucide-react';
import { RealDownloadAction } from '@/features/downloads/real-downloads';
import type { GameDetail } from '@/lib/data';

/**
 * Download-and-extract entry. Shown only where the work's capabilities allow it; Steam installs
 * and official-viewer-only works get no download button.
 */
export function DownloadAction({ game }: { game: GameDetail }) {
  if (game.capabilities.officialViewerOnly)
    return (
      <p className="hero-download is-note" data-testid="download-action">
        <BookLock size={14} />
        仅限 DLsite 官方阅读器查看 · Atlas 不提供下载，也不绕过授权
      </p>
    );
  // A work's capability can be unknown: the platform decides when asked, not Atlas.
  if (game.platform !== 'dlsite' || game.capabilities.download === false) return null;
  return <RealDownloadAction game={game} />;
}
