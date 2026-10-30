import * as TooltipPrimitive from '@radix-ui/react-tooltip';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Game } from '@/lib/data';
import { GameCard, GameCover } from './game-card';

const game: Game = {
  id: 'demo-unit',
  platform: 'steam',
  kind: 'game',
  maker: 'Atlas Original',
  releaseDate: null,
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
        <GameCard game={game} onFavorite={vi.fn()} href="/library/demo-unit" />
      </TooltipPrimitive.Provider>,
    );
    const heading = screen.getByRole('heading', { name: game.title });
    expect(within(heading).getByRole('link', { name: game.title })).toHaveAttribute(
      'href',
      '/library/demo-unit',
    );
    expect(screen.getByText('进行中')).toBeVisible();
    expect(screen.getByText('2 小时')).toBeVisible();
    expect(screen.getByText('已安装')).toBeVisible();
  });

  it('keeps favorite a separate control that does not open the detail', () => {
    const onFavorite = vi.fn();
    const onOpen = vi.fn();
    const pushState = vi.spyOn(window.history, 'pushState');
    render(
      <TooltipPrimitive.Provider>
        <GameCard game={game} onFavorite={onFavorite} href="/library/demo-unit" onOpen={onOpen} />
      </TooltipPrimitive.Provider>,
    );
    const button = screen.getByRole('button', { name: `收藏 ${game.title}` });
    fireEvent.click(button);
    expect(onFavorite).toHaveBeenCalledExactlyOnceWith('demo-unit');
    expect(button).toHaveAttribute('aria-pressed', 'false');
    expect(button.closest('a')).toBeNull();
    expect(onOpen).not.toHaveBeenCalled();
    expect(pushState).not.toHaveBeenCalled();
  });

  it('opens the detail in-app on a plain click and leaves modified clicks to the browser', () => {
    const onOpen = vi.fn();
    const pushState = vi.spyOn(window.history, 'pushState');
    render(
      <TooltipPrimitive.Provider>
        <GameCard game={game} onFavorite={vi.fn()} href="/library/demo-unit" onOpen={onOpen} />
      </TooltipPrimitive.Provider>,
    );
    const link = screen.getByRole('link', { name: game.title });
    fireEvent.click(link, { ctrlKey: true });
    expect(pushState).not.toHaveBeenCalled();
    fireEvent.click(link);
    expect(onOpen).toHaveBeenCalledOnce();
    expect(pushState).toHaveBeenCalledWith(
      { atlas: { fromLibrary: true } },
      '',
      '/library/demo-unit',
    );
    window.history.replaceState(null, '', '/');
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
