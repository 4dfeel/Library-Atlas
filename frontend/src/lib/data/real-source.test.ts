import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, resetApiSession, ServiceUnavailableError } from './api-client';
import { defaultLibraryFilters, GameUnavailableError, GameUpdateError } from './types';
import { RealLibrarySource } from './real-source';

const source = new RealLibrarySource();

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

const apiError = (code: string, status: number) =>
  json({ error: { code, message: `${code} message`, requestId: 'r', retryable: false } }, status);

const work = {
  id: 'w1',
  platform: 'dlsite',
  sourceId: 'RJ1',
  kind: 'other',
  maker: null,
  genre: null,
  subtitle: null,
  releaseDate: null,
  title: '未知字段样本',
  status: 'unplayed',
  installed: null,
  playtimeMinutes: null,
  favorite: false,
  visibility: 'normal',
  cover: { kind: 'missing', index: 0 },
  background: null,
  addedAt: '2026-10-30T00:00:00+00:00',
  lastPlayedAt: null,
  capabilities: { download: null, extract: null, officialViewerOnly: null },
  file: null,
};

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  resetApiSession();
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe('reading', () => {
  it('sends only the active filters and keeps unknown values unknown', async () => {
    fetchMock.mockResolvedValue(
      json({
        items: [work],
        offset: 100,
        limit: 100,
        filteredCount: 101,
        totalVisible: 101,
        genres: [],
        installedCount: 0,
        favoriteCount: 0,
        kindCounts: { game: 0, image: 0, video: 0, audio: 0, other: 101 },
      }),
    );
    const page = await source.listPage(
      { ...defaultLibraryFilters, search: ' 星 ', kind: 'non-game', favoritesOnly: true },
      100,
      100,
    );
    const url = new URL(String(fetchMock.mock.calls[0]![0]), 'http://x');
    expect(Object.fromEntries(url.searchParams)).toEqual({
      offset: '100',
      limit: '100',
      search: '星',
      kind: 'non-game',
      favoritesOnly: 'true',
    });
    expect(page.items[0]).toMatchObject({
      maker: '未提供',
      genre: '未分类',
      installed: null,
      playtimeMinutes: null,
    });
  });

  it('never turns a failed read into an empty result', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('network'));
    await expect(source.listPage(defaultLibraryFilters, 0, 100)).rejects.toBeInstanceOf(
      ServiceUnavailableError,
    );
    // A proxy with no backend answers without the service's error envelope.
    fetchMock.mockResolvedValueOnce(new Response('Bad Gateway', { status: 502 }));
    await expect(source.listPage(defaultLibraryFilters, 0, 100)).rejects.toBeInstanceOf(
      ServiceUnavailableError,
    );
    // A dev server's HTML fallback is not data either.
    fetchMock.mockResolvedValueOnce(
      new Response('<html></html>', { status: 200, headers: { 'content-type': 'text/html' } }),
    );
    await expect(source.listPage(defaultLibraryFilters, 0, 100)).rejects.toBeInstanceOf(
      ServiceUnavailableError,
    );
    fetchMock.mockResolvedValueOnce(apiError('service_not_ready', 503));
    await expect(source.listPage(defaultLibraryFilters, 0, 100)).rejects.toMatchObject({
      code: 'service_not_ready',
    });
  });

  it('lets an aborted request stay aborted', async () => {
    fetchMock.mockRejectedValueOnce(new DOMException('Aborted', 'AbortError'));
    await expect(source.getGame({ id: 'w1' })).rejects.toMatchObject({ name: 'AbortError' });
  });

  it('maps an unavailable work to the shared error', async () => {
    fetchMock.mockResolvedValueOnce(apiError('work_unavailable', 404));
    await expect(source.getGame({ id: 'a/b' })).rejects.toBeInstanceOf(GameUnavailableError);
    expect(fetchMock.mock.calls[0]![0]).toBe('/api/v1/works/a%2Fb');
  });

  it('reports readiness from a 503 instead of throwing it away', async () => {
    fetchMock.mockResolvedValueOnce(
      json({ status: 'not_ready', profile: 'real', reason: 'schema_too_new', message: 'm' }, 503),
    );
    await expect(source.ready()).resolves.toMatchObject({ reason: 'schema_too_new' });
    fetchMock.mockRejectedValueOnce(new TypeError('network'));
    await expect(source.ready()).rejects.toBeInstanceOf(ServiceUnavailableError);
  });
});

describe('writing', () => {
  const detail = {
    ...work,
    description: null,
    tags: [],
    categories: [],
    achievements: null,
    rating: 4,
    note: '',
    version: 2,
    files: [],
  };

  it('sends the CSRF token it was given', async () => {
    fetchMock
      .mockResolvedValueOnce(json({ csrfToken: 'token-1' }))
      .mockResolvedValueOnce(json(detail));
    const saved = await source.updateGame('w1', { rating: 4 });
    expect(saved.rating).toBe(4);
    const [path, init] = fetchMock.mock.calls[1]!;
    expect(path).toBe('/api/v1/works/w1/personal');
    expect(init?.method).toBe('PATCH');
    expect((init?.headers as Record<string, string>)['X-Atlas-CSRF']).toBe('token-1');
    expect(JSON.parse(String(init?.body))).toEqual({ rating: 4 });
  });

  it('fetches a new token once when the service restarted', async () => {
    fetchMock
      .mockResolvedValueOnce(json({ csrfToken: 'old' }))
      .mockResolvedValueOnce(apiError('csrf_invalid', 403))
      .mockResolvedValueOnce(json({ csrfToken: 'new' }))
      .mockResolvedValueOnce(json(detail));
    await source.updateGame('w1', { note: '保留' });
    const last = fetchMock.mock.calls[3]![1]!;
    expect((last.headers as Record<string, string>)['X-Atlas-CSRF']).toBe('new');
  });

  it('gives up after one token retry', async () => {
    fetchMock
      .mockResolvedValueOnce(json({ csrfToken: 'a' }))
      .mockResolvedValueOnce(apiError('csrf_invalid', 403))
      .mockResolvedValueOnce(json({ csrfToken: 'b' }))
      .mockResolvedValueOnce(apiError('csrf_invalid', 403));
    await expect(source.updateGame('w1', { note: 'x' })).rejects.toBeInstanceOf(GameUpdateError);
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it('reports a failed save as not saved', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('network'));
    await expect(source.updateGame('w1', { note: 'x' })).rejects.toThrow('修改尚未保存');
    fetchMock
      .mockResolvedValueOnce(json({ csrfToken: 't' }))
      .mockResolvedValueOnce(apiError('version_conflict', 409));
    await expect(source.updateGame('w1', { note: 'x' })).rejects.toThrow('version_conflict');
    expect(new ApiError('c', 'm', 500, true).retryable).toBe(true);
  });
});
