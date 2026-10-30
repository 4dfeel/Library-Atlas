import { useState } from 'react';
import { Download, ImageOff, Star } from 'lucide-react';
import { getCoverSource, useWorkspaceMode, type Game } from '@/lib/data';
import { availabilityLabel, statusLabels, workMeta } from '@/lib/utils';
import { AppLink } from '@/components/app-link';
import { Tooltip } from './ui/tooltip';

export function GameCover({
  game,
  compact = false,
  priority = false,
}: {
  game: Game;
  compact?: boolean;
  /** Above-the-fold detail cover: load eagerly instead of lazily. */
  priority?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  const source = getCoverSource(game);
  const isDemo = useWorkspaceMode() === 'demo';
  return (
    <div
      className={`game-cover${compact ? ' compact-cover' : ''}`}
      data-testid="game-cover"
      data-cover
      data-cover-kind={!source || failed ? 'missing' : game.cover.kind}
    >
      {source && !failed ? (
        <img
          src={source}
          alt={isDemo ? `${game.title} 演示封面` : `${game.title} 封面`}
          loading={priority ? 'eager' : 'lazy'}
          fetchPriority={priority ? 'high' : undefined}
          decoding="async"
          width="480"
          height="720"
          onError={() => setFailed(true)}
        />
      ) : (
        <div className="cover-placeholder" role="img" aria-label="暂无封面">
          <div className="placeholder-orbits" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <ImageOff size={compact ? 16 : 26} strokeWidth={1} />
          {!compact && (
            <>
              <span className="placeholder-letter">{game.title.slice(0, 1)}</span>
              <span className="placeholder-caption">封面待收录</span>
              <span className="placeholder-brand">LIBRARY ATLAS</span>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export function GameCard({
  game,
  onFavorite,
  href,
  onOpen,
}: {
  game: Game;
  onFavorite: (id: string) => void;
  href: string;
  onOpen?: () => void;
}) {
  const isDemo = useWorkspaceMode() === 'demo';
  const savedNote = isDemo ? ' · 演示修改保存在本机' : '';
  return (
    <article className="game-card" data-testid="game-card" data-game-card data-game-id={game.id}>
      <div className="card-art">
        <GameCover game={game} />
        <div className="card-cover-shade" />
        {game.installed && (
          <span className="installed-badge">
            <Download size={12} />
            {availabilityLabel(game)}
          </span>
        )}
        <Tooltip content={`${game.favorite ? '取消收藏' : '收藏作品'}${savedNote}`}>
          <button
            data-focus-key="favorite"
            className={`favorite-button${game.favorite ? ' is-favorite' : ''}`}
            aria-label={`${game.favorite ? '取消收藏' : '收藏'} ${game.title}`}
            aria-pressed={game.favorite}
            onClick={() => onFavorite(game.id)}
          >
            <Star size={16} fill={game.favorite ? 'currentColor' : 'none'} />
          </button>
        </Tooltip>
      </div>
      <div className="game-card-body">
        <h3 className="game-title" data-testid="game-title">
          <Tooltip
            content={
              <>
                <strong>{game.title}</strong>
                <span className="tooltip-description">打开作品详情</span>
              </>
            }
          >
            <AppLink
              to={href}
              state={{ fromLibrary: true }}
              onNavigate={onOpen}
              className="game-link"
              data-focus-key="title"
            >
              {game.title}
            </AppLink>
          </Tooltip>
        </h3>
        <div className="game-card-meta">
          <span>{workMeta(game)}</span>
          <span className={`status-label status-${game.status}`}>
            <i className="status-dot" />
            {statusLabels[game.status]}
          </span>
        </div>
      </div>
    </article>
  );
}
