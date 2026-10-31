import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { DownloadTask, ExtractTask } from '@/lib/data';
import { DownloadsPage } from './downloads-page';

const task = (values: Partial<DownloadTask>): DownloadTask => ({
  id: 't1',
  workId: 'w1',
  title: '合成作品',
  part: null,
  partCount: null,
  state: 'downloading',
  bytesDone: 1024 * 1024,
  bytesTotal: null,
  fileName: null,
  code: null,
  message: null,
  canRetry: false,
  canResume: false,
  integrity: null,
  location: null,
  fileMissing: false,
  archiveRemoved: false,
  dismissed: false,
  bytesPerSecond: null,
  createdAt: '2026-10-31T00:00:00Z',
  finishedAt: null,
  ...values,
});

function show(tasks: DownloadTask[], extractions: ExtractTask[] = []) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      Response.json({
        tasks: String(url).includes('extractions') ? extractions : tasks,
        activeCount: tasks.filter((entry) => entry.state === 'downloading').length,
        updates: [],
      }),
    ),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <DownloadsPage />
    </QueryClientProvider>,
  );
}

describe('the download queue', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('opens the work from its cover', async () => {
    show([task({ state: 'done', bytesDone: 10, fileName: 'a.zip' })]);
    const title = await screen.findByText('合成作品');
    const cover = title.closest('li')!.querySelector('.queue-row-cover')!;
    expect(cover.closest('a')).toHaveAttribute('href', '/library/w1');
    expect(cover.closest('a')).toHaveAttribute('tabindex', '-1');
  });

  it('says the total is unknown and shows no made-up number', async () => {
    show([task({})]);
    const row = await screen.findByText('已下载 1 MB · 总大小未知');
    expect(row).toBeInTheDocument();
    const bar = screen.getByRole('progressbar');
    expect(bar).not.toHaveAttribute('aria-valuenow');
    expect(bar).toHaveAttribute('aria-valuetext', '下载中，总大小未知');
  });

  it('shows real progress when the total is known', async () => {
    show([task({ bytesDone: 50, bytesTotal: 200 })]);
    expect(await screen.findByRole('progressbar')).toHaveAttribute('aria-valuenow', '25');
  });

  it('offers to continue only when the service says it can', async () => {
    show([
      task({ id: 'a', title: '可续传', state: 'interrupted', canRetry: true, canResume: true }),
      task({ id: 'b', title: '要重来', state: 'interrupted', canRetry: true }),
      task({ id: 'c', title: '别的账号', state: 'failed', message: '不能继续' }),
    ]);
    const rowOf = (name: string) => screen.getByText(name).closest('li')!;
    await screen.findByText('可续传');
    expect(within(rowOf('可续传')).getByRole('button', { name: '继续' })).toBeInTheDocument();
    expect(within(rowOf('要重来')).getByRole('button', { name: '重新下载' })).toBeInTheDocument();
    expect(within(rowOf('要重来')).queryByRole('button', { name: '继续' })).toBeNull();
    expect(within(rowOf('别的账号')).queryByRole('button', { name: /继续|重新下载/ })).toBeNull();
  });

  it('calls a finished file downloaded, never installed', async () => {
    show([
      task({
        state: 'done',
        bytesDone: 1024,
        bytesTotal: 1024,
        fileName: 'a.zip',
        integrity: 'stream_end',
      }),
    ]);
    const dialog = await screen.findByTestId('downloads-page');
    expect(await within(dialog).findAllByText('已下载')).not.toHaveLength(0);
    expect(within(dialog).getByText('完整性保障有限')).toBeInTheDocument();
    expect(dialog).not.toHaveTextContent('已安装');
    expect(dialog).not.toHaveTextContent('可玩');
  });

  it('keeps a failed unpacking apart from the finished download', async () => {
    const failed: ExtractTask = {
      id: 'x',
      workId: 'w1',
      title: '解压作品',
      state: 'failed',
      format: 'rar',
      filesTotal: 3,
      bytesTotal: 2048,
      bytesDone: 0,
      code: 'encrypted',
      message: '这个压缩包有密码，暂不支持。',
      canRetry: true,
      location: null,
      resultMissing: false,
      cleanupFailed: false,
      dismissed: false,
      createdAt: '2026-10-31T00:00:00Z',
      finishedAt: null,
    };
    show([task({ state: 'done', bytesDone: 10, fileName: 'a.zip' })], [failed]);
    expect(await screen.findByText('这个压缩包有密码，暂不支持。')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重新解压' })).toBeInTheDocument();
    expect(screen.getByText('已完成', { exact: false })).toBeInTheDocument();
  });

  it('says so when a finished file has been moved', async () => {
    show([task({ state: 'done', bytesDone: 10, fileName: 'a.zip', fileMissing: true })]);
    expect(await screen.findByText('文件已经不在原位置')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '打开文件夹' })).toBeNull();
  });
});
