import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const settled = (scope: HTMLElement) =>
  waitFor(() => expect(within(scope).queryByText('正在保存…')).not.toBeInTheDocument());
import { GameUpdateError, useGameDetail, type GameDetail, type GameUpdate } from '@/lib/data';
import { realSource } from '@/lib/data/real-source';
import { PersonalRecord } from './personal-record';
import { noteDrafts } from './note-drafts';

const blank: GameDetail = {
  id: 'syn-1',
  platform: 'steam',
  sourceId: '1',
  capabilities: { download: false, extract: false, officialViewerOnly: false },
  file: null,
  kind: 'game',
  maker: '示例工作室',
  releaseDate: null,
  title: '合成样本',
  subtitle: '',
  genre: '冒险',
  status: 'unplayed',
  installed: null,
  playtimeMinutes: null,
  favorite: false,
  visibility: 'normal',
  cover: { kind: 'missing', index: 0 },
  addedAt: '2026-01-01T00:00:00Z',
  lastPlayedAt: null,
  description: null,
  tags: [],
  categories: [],
  achievements: null,
  rating: null,
  note: '',
  version: 1,
};

/** What the local service would hold, so a test can look at what was really saved. */
let saved: GameDetail;
let failWrites = false;

function Harness({ id, notify }: { id: string; notify: (message: string) => void }) {
  const query = useGameDetail(id);
  return query.data ? <PersonalRecord game={query.data} notify={notify} /> : null;
}

function renderRecord(id: string) {
  const notify = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Harness id={id} notify={notify} />
    </QueryClientProvider>,
  );
  return { notify, user: userEvent.setup() };
}

beforeEach(() => {
  saved = { ...blank };
  failWrites = false;
  noteDrafts.clear();
  vi.spyOn(realSource, 'getGame').mockImplementation(async () => saved);
  vi.spyOn(realSource, 'updateGame').mockImplementation(async (_id, update: GameUpdate) => {
    await new Promise((done) => setTimeout(done, 150));
    if (failWrites) throw new GameUpdateError('尚未保存，请重试');
    saved = { ...saved, ...update, version: (saved.version ?? 0) + 1 } as GameDetail;
    return saved;
  });
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe('personal record', () => {
  it('cancels a note draft without saving and returns focus to the entry button', async () => {
    const { user } = renderRecord('syn-1');
    await user.click(await screen.findByRole('button', { name: '添加备注' }));
    const input = screen.getByRole('textbox', { name: /个人备注/ });
    expect(input).toHaveFocus();
    await user.type(input, '还没想好');
    expect(screen.getByText('有未保存的修改')).toBeVisible();
    await user.click(screen.getByRole('button', { name: '取消' }));
    expect(screen.getByText(/还没有备注/)).toBeVisible();
    await waitFor(() => expect(screen.getByRole('button', { name: '添加备注' })).toHaveFocus());
    expect(saved.note).toBe('');
  });

  it('saves a note with Ctrl+Enter only after the write succeeds', async () => {
    const { user, notify } = renderRecord('syn-1');
    await user.click(await screen.findByRole('button', { name: '添加备注' }));
    await user.type(screen.getByRole('textbox', { name: /个人备注/ }), '周末继续第二章');
    await user.keyboard('{Control>}{Enter}{/Control}');
    expect(screen.getByText('正在保存…')).toBeVisible();
    expect(await screen.findByText('已保存')).toBeVisible();
    expect(screen.queryByRole('textbox', { name: /个人备注/ })).not.toBeInTheDocument();
    expect(screen.getByText('周末继续第二章')).toHaveClass('note-text');
    expect(notify).toHaveBeenCalledWith('备注已保存');
    expect(saved.note).toBe('周末继续第二章');
  });

  it('keeps the draft and shows an error when saving fails', async () => {
    failWrites = true;
    const { user } = renderRecord('syn-1');
    await user.click(await screen.findByRole('button', { name: '添加备注' }));
    await user.type(screen.getByRole('textbox', { name: /个人备注/ }), '这条会失败');
    await user.click(screen.getByRole('button', { name: '保存备注' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('尚未保存');
    expect(screen.getByRole('textbox', { name: /个人备注/ })).toHaveValue('这条会失败');
    expect(screen.queryByText('已保存')).not.toBeInTheDocument();
    expect(noteDrafts.get('syn-1')).toBe('这条会失败');
  });

  it('sets, changes and clears the 1–5 star rating', async () => {
    const { user } = renderRecord('syn-1');
    const stars = await screen.findByRole('group', { name: /个人评分/ });
    expect(within(stars).getByText('未评分')).toBeVisible();
    await user.click(within(stars).getByRole('radio', { name: '4 星' }));
    expect(await within(stars).findByText('4 / 5')).toBeVisible();
    await settled(stars);
    await user.click(within(stars).getByRole('radio', { name: '2 星' }));
    expect(await within(stars).findByText('2 / 5')).toBeVisible();
    await settled(stars);
    await user.click(within(stars).getByRole('button', { name: /清除评分/ }));
    expect(await within(stars).findByText('未评分')).toBeVisible();
    await settled(stars);
    expect(saved.rating).toBeNull();
  });

  it('saves a status change to the library', async () => {
    const { user } = renderRecord('syn-1');
    const status = await screen.findByRole('group', { name: '进度状态' });
    await user.click(within(status).getByRole('radio', { name: '搁置' }));
    expect(await within(status).findByText('已保存')).toBeVisible();
    expect(within(status).getByRole('radio', { name: '搁置' })).toBeChecked();
    expect(saved.status).toBe('paused');
  });
});
