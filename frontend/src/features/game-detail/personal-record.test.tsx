import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const settled = (scope: HTMLElement) =>
  waitFor(() => expect(within(scope).queryByText('正在保存…')).not.toBeInTheDocument());
import { defaultLibraryFilters, useGameDetail } from '@/lib/data';
import { getDemoSource } from '@/lib/data/demo-source';
import { PersonalRecord } from './personal-record';
import { noteDrafts } from './note-drafts';

function Harness({ id, notify }: { id: string; notify: (message: string) => void }) {
  const query = useGameDetail(id, { size: 1500 });
  return query.data ? <PersonalRecord game={query.data} size={1500} notify={notify} /> : null;
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

beforeEach(async () => {
  await getDemoSource(1500).resetEdits();
  noteDrafts.clear();
});
afterEach(() => {
  getDemoSource(1500).failWrites = false;
});

describe('personal record (demo)', () => {
  it('cancels a note draft without saving and returns focus to the entry button', async () => {
    const { user } = renderRecord('demo-00003');
    await user.click(await screen.findByRole('button', { name: '添加备注' }));
    const input = screen.getByRole('textbox', { name: /个人备注/ });
    expect(input).toHaveFocus();
    await user.type(input, '还没想好');
    expect(screen.getByText('有未保存的修改')).toBeVisible();
    await user.click(screen.getByRole('button', { name: '取消' }));
    expect(screen.getByText(/还没有备注/)).toBeVisible();
    await waitFor(() => expect(screen.getByRole('button', { name: '添加备注' })).toHaveFocus());
    expect((await getDemoSource(1500).getGame({ id: 'demo-00003' })).note).toBe('');
  });

  it('saves a note with Ctrl+Enter only after the write succeeds', async () => {
    const { user, notify } = renderRecord('demo-00003');
    await user.click(await screen.findByRole('button', { name: '添加备注' }));
    await user.type(screen.getByRole('textbox', { name: /个人备注/ }), '周末继续第二章');
    await user.keyboard('{Control>}{Enter}{/Control}');
    expect(screen.getByText('正在保存…')).toBeVisible();
    expect(await screen.findByText('已保存到本机演示存储')).toBeVisible();
    expect(screen.queryByRole('textbox', { name: /个人备注/ })).not.toBeInTheDocument();
    expect(screen.getByText('周末继续第二章')).toHaveClass('note-text');
    expect(notify).toHaveBeenCalledWith('备注已保存到本机演示存储');
    expect((await getDemoSource(1500).getGame({ id: 'demo-00003' })).note).toBe('周末继续第二章');
  });

  it('keeps the draft and shows an error when saving fails', async () => {
    getDemoSource(1500).failWrites = true;
    const { user } = renderRecord('demo-00003');
    await user.click(await screen.findByRole('button', { name: '添加备注' }));
    await user.type(screen.getByRole('textbox', { name: /个人备注/ }), '这条会失败');
    await user.click(screen.getByRole('button', { name: '保存备注' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('尚未保存');
    expect(screen.getByRole('textbox', { name: /个人备注/ })).toHaveValue('这条会失败');
    expect(screen.queryByText('已保存到本机演示存储')).not.toBeInTheDocument();
    expect(noteDrafts.get('demo-00003')).toBe('这条会失败');
  });

  it('sets, changes and clears the 1–5 star rating', async () => {
    const { user } = renderRecord('demo-00003');
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
    expect((await getDemoSource(1500).getGame({ id: 'demo-00003' })).rating).toBeNull();
  });

  it('changes status through the shared source used by the Library', async () => {
    const { user } = renderRecord('demo-00001');
    const status = await screen.findByRole('group', { name: '进度状态' });
    await user.click(within(status).getByRole('radio', { name: '搁置' }));
    expect(await within(status).findByText('已保存到本机演示存储')).toBeVisible();
    expect(within(status).getByRole('radio', { name: '搁置' })).toBeChecked();
    const list = await getDemoSource(1500).list({
      filters: { ...defaultLibraryFilters, search: '星穹观测站', status: 'paused' },
    });
    expect(list.items.map((game) => game.id)).toEqual(['demo-00001']);
  });
});
