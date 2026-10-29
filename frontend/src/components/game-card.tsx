import { useState } from 'react';
import { Download, ImageOff, Star } from 'lucide-react';
import { getCoverSource, type Game } from '@/lib/data';
import { formatPlaytime, statusLabels } from '@/lib/utils';
import { Tooltip } from './ui/tooltip';

export function GameCover({ game, compact = false }: { game: Game; compact?: boolean }) {
  const [failed, setFailed] = useState(false);
  const source = getCoverSource(game);
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
          alt={`${game.title} 演示封面`}
          loading="lazy"
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

export function GameCard({ game, onFavorite }: { game: Game; onFavorite: (id: string) => void }) {
  return (
    <article className="game-card" data-testid="game-card" data-game-card data-game-id={game.id}>
      <div className="card-art">
        <GameCover game={game} />
        <div className="card-cover-shade" />
        {game.installed && (
          <span className="installed-badge">
            <Download size={12} />
            已安装
          </span>
        )}
        <Tooltip
          content={game.favorite ? '取消收藏 · 仅本次演示会话' : '收藏游戏 · 仅本次演示会话'}
        >
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
        <Tooltip
          content={
            <>
              <strong>{game.title}</strong>
              <span className="tooltip-description">详情页将在后续检查点开放</span>
            </>
          }
        >
          <h3
            tabIndex={0}
            className="game-title"
            data-focus-key="title"
            data-testid="game-title"
            aria-label={game.title}
          >
            {game.title}
          </h3>
        </Tooltip>
        <div className="game-card-meta">
          <span>{formatPlaytime(game.playtimeMinutes)}</span>
          <span className={`status-label status-${game.status}`}>
            <i className="status-dot" />
            {statusLabels[game.status]}
          </span>
        </div>
      </div>
    </article>
  );
}
