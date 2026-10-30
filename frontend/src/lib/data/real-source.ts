import { apiGet, ApiError, apiWrite, ServiceUnavailableError } from './api-client';
import type { DashboardRequest, DashboardResult } from './dashboard';
import {
  GameUnavailableError,
  GameUpdateError,
  type Game,
  type GameDetail,
  type GameRequest,
  type GameUpdate,
  type LibraryFilters,
  type LibrarySource,
  type Platform,
  type WorkKind,
  type WorkFileInfo,
} from './types';

export const realPageSize = 100;

/** Wire shape of a work; see docs/LOCAL_API.md. */
type ApiWork = Omit<Game, 'maker' | 'genre' | 'subtitle'> & {
  maker: string | null;
  genre: string | null;
  subtitle: string | null;
};
type ApiWorkDetail = ApiWork &
  Pick<GameDetail, 'description' | 'tags' | 'categories' | 'achievements' | 'rating' | 'note'> & {
    version: number;
    files: WorkFileInfo[];
  };

export interface LibrarySummary {
  totalVisible: number;
  filteredCount: number;
  genres: string[];
  installedCount: number;
  favoriteCount: number;
  kindCounts: Record<WorkKind, number>;
}

export interface WorkPage extends LibrarySummary {
  items: Game[];
  offset: number;
  limit: number;
}

type ApiWorkPage = Omit<WorkPage, 'items'> & { items: ApiWork[] };
type ApiDashboard = Omit<
  DashboardResult,
  'featured' | 'recent' | 'mostPlayed' | 'recommendations'
> & {
  featured: ApiWork[];
  recent: ApiWork[];
  mostPlayed: ApiWork[];
  recommendations: { game: ApiWork; reasons: string[] }[];
};

export type ConnectionStatus = 'not_connected' | 'connected' | 'reauth_required' | 'error';

export interface SourceStatus {
  id: Platform;
  displayName: string;
  connection: ConnectionStatus;
  workCount: number;
  lastSyncAt: string | null;
  capabilities: { connect: boolean; sync: boolean; download: boolean };
}

export interface ServiceReady {
  status: 'ready' | 'not_ready';
  profile: 'real' | 'test';
  schemaRevision?: string;
  reason?: string;
  message?: string;
}

/** Missing text is shown as missing; the display defaults never pretend to be source data. */
function toGame(work: ApiWork): Game {
  return {
    ...work,
    maker: work.maker ?? '未提供',
    genre: work.genre ?? '未分类',
    subtitle: work.subtitle ?? '',
  };
}

function toDetail(work: ApiWorkDetail): GameDetail {
  return { ...work, ...toGame(work) };
}

function filterParams(filters: LibraryFilters, offset: number, limit: number) {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  if (filters.search.trim()) params.set('search', filters.search.trim());
  if (filters.kind !== 'all') params.set('kind', filters.kind);
  if (filters.platform !== 'all') params.set('platform', filters.platform);
  if (filters.genre !== 'all') params.set('genre', filters.genre);
  if (filters.status !== 'all') params.set('status', filters.status);
  if (filters.installed !== 'all') params.set('installed', filters.installed);
  if (filters.favoritesOnly) params.set('favoritesOnly', 'true');
  if (filters.sort !== 'curated') params.set('sort', filters.sort);
  return params;
}

const workPath = (id: string) => `/api/v1/works/${encodeURIComponent(id)}`;

function saveError(error: unknown): unknown {
  if (error instanceof ApiError && error.code === 'work_unavailable')
    return new GameUnavailableError();
  if (error instanceof ServiceUnavailableError)
    return new GameUpdateError('本地服务没有响应，修改尚未保存。');
  if (error instanceof ApiError) return new GameUpdateError(error.message);
  return error;
}

export class RealLibrarySource implements LibrarySource {
  readonly mode = 'real' as const;

  async listPage(
    filters: LibraryFilters,
    offset: number,
    limit: number,
    signal?: AbortSignal,
  ): Promise<WorkPage> {
    const page = await apiGet<ApiWorkPage>(
      '/api/v1/works',
      filterParams(filters, offset, limit),
      signal,
    );
    return { ...page, items: page.items.map(toGame) };
  }

  async getGame({ id, signal }: GameRequest): Promise<GameDetail> {
    try {
      return toDetail(await apiGet<ApiWorkDetail>(workPath(id), undefined, signal));
    } catch (error) {
      if (error instanceof ApiError && error.code === 'work_unavailable')
        throw new GameUnavailableError();
      throw error;
    }
  }

  async updateGame(id: string, update: GameUpdate): Promise<GameDetail> {
    try {
      return toDetail(await apiWrite<ApiWorkDetail>('PATCH', `${workPath(id)}/personal`, update));
    } catch (error) {
      throw saveError(error);
    }
  }

  async toggleFavorite(id: string): Promise<void> {
    try {
      await apiWrite('POST', `${workPath(id)}/favorite/toggle`);
    } catch (error) {
      throw saveError(error);
    }
  }

  async dashboard({ scope, batch = 0, signal }: DashboardRequest): Promise<DashboardResult> {
    const params = new URLSearchParams({ scope, batch: String(batch) });
    const data = await apiGet<ApiDashboard>('/api/v1/dashboard', params, signal);
    return {
      ...data,
      featured: data.featured.map(toGame),
      recent: data.recent.map(toGame),
      mostPlayed: data.mostPlayed.map(toGame),
      recommendations: data.recommendations.map(({ game, reasons }) => ({
        game: toGame(game),
        reasons,
      })),
    };
  }

  async sources(signal?: AbortSignal): Promise<SourceStatus[]> {
    return (await apiGet<{ sources: SourceStatus[] }>('/api/v1/sources', undefined, signal))
      .sources;
  }

  /** A 503 still carries the reason, which is what the page needs to show. */
  async ready(signal?: AbortSignal): Promise<ServiceReady> {
    let response: Response;
    try {
      response = await fetch('/api/v1/ready', { signal });
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') throw error;
      throw new ServiceUnavailableError();
    }
    const body = (await response.json().catch(() => null)) as ServiceReady | null;
    if (!body?.status) throw new ServiceUnavailableError();
    return body;
  }
}

export const realSource = new RealLibrarySource();
