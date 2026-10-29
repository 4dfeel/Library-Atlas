import * as TooltipPrimitive from '@radix-ui/react-tooltip';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Game } from '@/lib/data';
import { GameCard, GameCover } from './game-card';

const game: Game = {
  id: 'demo-unit',
  title: '跨越银河之后的漫长旅途 / A Very Long Journey 日本語 Special Edition',
  subtitle: '',
  genre: '冒险',
  status: 'playing',
  installed: true,
  playtimeMinutes: 120,
  favorite: false,
  visibility: 'normal',
  cover: { kind: 'art', index: 0 },
  background: null,
  addedAt: '2026-01-01T00:00:00Z',
  lastPlayedAt: null,
};

describe('GameCard', () => {
  it('keeps the complete title accessible and exposes a visible status with its playtime', () => {
    render(
      <TooltipPrimitive.Provider>
        <GameCard game={game} onFavorite={vi.fn()} />
      </TooltipPrimitive.Provider>,
    );
    expect(screen.getByRole('heading', { name: game.title })).toHaveAttribute('tabindex', '0');
    expect(screen.getByText('在玩')).toBeVisible();
    expect(screen.getByText('2 小时')).toBeVisible();
    expect(screen.getByText('已安装')).toBeVisible();
  });

  it('updates favorites via the data boundary callback rather than pretending detail is implemented', () => {
    const onFavorite = vi.fn();
    render(
      <TooltipPrimitive.Provider>
        <GameCard game={game} onFavorite={onFavorite} />
      </TooltipPrimitive.Provider>,
    );
    const button = screen.getByRole('button', { name: `收藏 ${game.title}` });
    fireEvent.click(button);
    expect(onFavorite).toHaveBeenCalledExactlyOnceWith('demo-unit');
    expect(button).toHaveAttribute('aria-pressed', 'false');
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('uses the same local placeholder for absent and failed images', () => {
    const { rerender } = render(
      <GameCover game={{ ...game, cover: { kind: 'missing', index: 0 } }} />,
    );
    expect(screen.getByRole('img', { name: '暂无封面' })).toBeVisible();
    rerender(<GameCover game={game} />);
    fireEvent.error(screen.getByRole('img', { name: `${game.title} 演示封面` }));
    expect(screen.getByRole('img', { name: '暂无封面' })).toBeVisible();
    expect(screen.getByTestId('game-cover')).toHaveAttribute('data-cover-kind', 'missing');
  });
});
