import { useState, type MouseEvent, type ReactNode, type Ref } from 'react';
import { ExternalLink, ArrowLeft, Download, HardDrive, Star, Trophy } from 'lucide-react';
import { GameCover } from '@/components/game-card';
import { Button } from '@/components/ui/button';
import {
  getCoverSource,
  useUpdateGame,
  useWorkGallery,
  useWorkspace,
  type Game,
  type GameDetail,
} from '@/lib/data';
import { AppLink } from '@/components/app-link';
import { CloudSavePanel } from './cloud-save';
import { DownloadAction } from './download-action';
import { GameUpdatePanel } from './game-update';
import { LocalCopyPanel } from './local-copy';
import { PlayRecord } from './play-record';
import {
  availabilityLabel,
  formatDate,
  kindLabels,
  platformLabels,
  statusLabels,
  usageVerbs,
} from '@/lib/utils';

type Notify = (message: string, tone?: 'success' | 'error') => void;

function ContourPattern() {
  return (
    <svg className="hero-contours" viewBox="0 0 800 400" preserveAspectRatio="xMidYMid slice">
      {Array.from({ length: 9 }, (_, index) => (
        <ellipse
          key={index}
          cx="610"
          cy="170"
          rx={70 + index * 58}
          ry={34 + index * 27}
          transform={`rotate(-14 610 170)`}
        />
      ))}
    </svg>
  );
}

/**
 * One of the work's store images, frosted, chosen afresh each time the page opens. Never the
 * cover. A wide image suits a wide banner, so an upright one is used only when there is nothing
 * else. Without any, the pattern stands in.
 */
function StoreBackdrop({ workId }: { workId: string }) {
  const { gallery } = useWorkGallery(workId);
  const [pick] = useState(() => Math.random());
  const [failed, setFailed] = useState<string[]>([]);
  // The platform does not always give sizes, so an upright one may only show itself on arrival.
  const [upright, setUpright] = useState<string[]>([]);
  const usable = (gallery?.images ?? []).filter((image) => !failed.includes(image.url));
  const wide = usable.filter(
    (image) => !upright.includes(image.url) && (image.width ?? 1) >= (image.height ?? 1),
  );
  const pool = wide.length ? wide : usable;
  const chosen = pool[Math.floor(pick * pool.length)];
  if (!chosen)
    return (
      <div className="hero-backdrop hero-fallback" data-backdrop="pattern" aria-hidden="true">
        <ContourPattern />
      </div>
    );
  return (
    <div className="hero-backdrop" data-backdrop="store" aria-hidden="true">
      <img
        key={chosen.url}
        src={chosen.url}
        alt=""
        decoding="async"
        fetchPriority="high"
        onError={() => setFailed([...failed, chosen.url])}
        onLoad={(event) => {
          const { naturalWidth, naturalHeight } = event.currentTarget;
          if (naturalHeight > naturalWidth) setUpright([...upright, chosen.url]);
        }}
      />
    </div>
  );
}

/**
 * An ambient wash from the cover, or the Atlas contour pattern when there is no cover.
 * A failed image falls back once.
 */
export function HeroBackdrop({ game }: { game: Game }) {
  const cover = getCoverSource(game);
  const [coverFailed, setCoverFailed] = useState(false);
  const ambient = cover && !coverFailed;
  return (
    <div
      className="hero-backdrop hero-fallback"
      data-backdrop={ambient ? 'ambient' : 'pattern'}
      aria-hidden="true"
    >
      {ambient && <img src={cover} alt="" decoding="async" onError={() => setCoverFailed(true)} />}
      <ContourPattern />
    </div>
  );
}

function formatHours(minutes: number) {
  if (minutes < 60) return { value: String(minutes), unit: '分钟' };
  return {
    value: (minutes / 60).toLocaleString('zh-CN', { maximumFractionDigits: 1 }),
    unit: '小时',
  };
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="hero-fact">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

export function GameHero({
  game,
  notify,
  backHref,
  onBack,
  backLabel,
  headingRef,
}: {
  game: GameDetail;
  notify: Notify;
  backHref: string;
  onBack: (event: MouseEvent<HTMLAnchorElement>) => void;
  backLabel: string;
  headingRef: Ref<HTMLHeadingElement>;
}) {
  const { isTestLibrary } = useWorkspace();
  const favorite = useUpdateGame(game.id);
  const isFavorite = favorite.isPending
    ? (favorite.variables.favorite ?? game.favorite)
    : game.favorite;
  const titleLength = Array.from(game.title).length;
  const titleClass = titleLength > 60 ? ' title-xlong' : titleLength > 28 ? ' title-long' : '';
  // Only Steam reports play time and achievements; other platforms show metadata.
  const tracksPlay = game.platform === 'steam' || game.kind === 'game';
  const lastPlayed = formatDate(game.lastPlayedAt);
  const achievements = game.achievements;
  const percent =
    achievements && achievements.total > 0
      ? Math.round((achievements.unlocked / achievements.total) * 100)
      : null;

  return (
    <header className="detail-hero" aria-labelledby="detail-title">
      <StoreBackdrop workId={game.id} />
      <div className="hero-scrim" aria-hidden="true" />
      <div className="detail-frame hero-inner">
        <AppLink to={backHref} className="back-link" onClick={onBack} data-testid="back-to-library">
          <ArrowLeft size={16} />
          {backLabel}
        </AppLink>
        <div className="hero-main">
          <div className="hero-cover">
            <GameCover game={game} priority />
          </div>
          <div className="hero-copy">
            <div className="hero-eyebrow">
              {isTestLibrary && <span className="sample-chip">测试数据 · 合成样本</span>}
              <span className="platform-chip" data-platform={game.platform}>
                {platformLabels[game.platform]}
              </span>
              <span>
                {kindLabels[game.kind]} · {game.genre}
              </span>
              {game.subtitle && <span className="hero-subtitle">{game.subtitle}</span>}
            </div>
            <h1
              id="detail-title"
              ref={headingRef}
              tabIndex={-1}
              className={`detail-title${titleClass}`}
              data-testid="detail-title"
            >
              {game.title}
            </h1>
            <div className="hero-badges">
              <span className={`hero-status status-${game.status}`} data-testid="detail-status">
                <i className="status-dot" />
                {statusLabels[game.status]}
              </span>
              <span className={`hero-install${game.installed ? ' is-installed' : ''}`}>
                {game.installed ? <Download size={13} /> : <HardDrive size={13} />}
                {availabilityLabel(game)}
              </span>
            </div>
            <div className="hero-actions">
              <Button
                variant="secondary"
                aria-pressed={isFavorite}
                className={isFavorite ? 'is-favorite' : ''}
                disabled={favorite.isPending}
                onClick={() =>
                  favorite.mutate(
                    { favorite: !isFavorite },
                    {
                      onSuccess: () => notify(isFavorite ? '已取消收藏' : '已加入收藏'),
                      onError: () => notify('未能更新收藏，请重试', 'error'),
                    },
                  )
                }
              >
                <Star size={16} fill={isFavorite ? 'currentColor' : 'none'} />
                {isFavorite ? '已收藏' : '收藏'}
              </Button>
              {game.sourceUrl && (
                <a
                  className="store-button"
                  href={game.sourceUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  data-testid="store-button"
                >
                  <ExternalLink size={15} />
                  官方商店
                </a>
              )}
            </div>
            <DownloadAction game={game} />
            <LocalCopyPanel game={game} />
            <GameUpdatePanel game={game} />
            <CloudSavePanel game={game} />
            <PlayRecord game={game} />
            <dl className="hero-facts">
              {tracksPlay ? (
                <>
                  <Fact label="累计游玩">
                    {game.playtimeMinutes === null ? (
                      <span className="fact-empty">还没有记录</span>
                    ) : game.playtimeMinutes === 0 ? (
                      <span className="fact-empty">尚未开始</span>
                    ) : (
                      <>
                        <strong>{formatHours(game.playtimeMinutes).value}</strong>
                        <span className="fact-unit">{formatHours(game.playtimeMinutes).unit}</span>
                      </>
                    )}
                  </Fact>
                  <Fact label="最近游玩">
                    {lastPlayed ? (
                      <strong className="fact-date">{lastPlayed}</strong>
                    ) : (
                      <span className="fact-empty">暂无记录</span>
                    )}
                  </Fact>
                  {game.platform === 'steam' && (
                    <Fact label="成就进度">
                      {achievements ? (
                        <>
                          <strong>{achievements.unlocked}</strong>
                          <span className="fact-unit">/ {achievements.total}</span>
                          <span className="fact-percent">
                            <Trophy size={13} />
                            {percent}%
                          </span>
                        </>
                      ) : (
                        <span className="fact-empty">未提供</span>
                      )}
                    </Fact>
                  )}
                </>
              ) : (
                // The platform reports no play history or achievements; show what it does.
                <>
                  <Fact label="作品类型">
                    <strong className="fact-date">{kindLabels[game.kind]}</strong>
                  </Fact>
                  {/* Same usage record the Dashboard's recent row uses; maker is in the archive. */}
                  <Fact label={`最近${usageVerbs[game.kind]}`}>
                    {lastPlayed ? (
                      <strong className="fact-date">{lastPlayed}</strong>
                    ) : (
                      <span className="fact-empty">暂无记录</span>
                    )}
                  </Fact>
                  <Fact label="发售日">
                    {formatDate(game.releaseDate) ? (
                      <strong className="fact-date">{formatDate(game.releaseDate)}</strong>
                    ) : (
                      <span className="fact-empty">未提供</span>
                    )}
                  </Fact>
                </>
              )}
              <Fact label="加入作品库">
                <strong className="fact-date">{formatDate(game.addedAt) ?? '未记录'}</strong>
              </Fact>
            </dl>
          </div>
        </div>
      </div>
    </header>
  );
}
