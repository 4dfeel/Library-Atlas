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

export type ConnectionStatus =
  | 'not_connected'
  | 'authenticating'
  | 'needs_verification'
  | 'verifying'
  | 'connected'
  | 'unverified'
  | 'reauth_required'
  | 'disconnect_failed'
  | 'error';

/** Safe to show: never the account name, session or anything from the platform. */
export interface DlsiteConnection {
  state: ConnectionStatus;
  code?: string;
  message?: string;
  lastVerifiedAt?: string;
  canReveal?: boolean;
  /** Masked; absent after web login, where Atlas never sees the account name. */
  accountAlias?: string;
  /** Masked name of a remembered login. The password never comes to the page. */
  rememberedAccount?: string;
}

export interface FolderInfo {
  kind: 'library' | 'download_cache';
  path: string | null;
  isDefault: boolean;
  status: 'ok' | 'not_set' | 'missing';
}

export interface SourceStatus {
  id: Platform;
  displayName: string;
  connection: ConnectionStatus;
  workCount: number;
  lastSyncAt: string | null;
  capabilities: { connect: boolean; sync: boolean; download: boolean };
}

export type SyncState =
  | 'preparing'
  | 'reading'
  | 'saving'
  | 'succeeded'
  | 'partial'
  | 'failed'
  | 'cancelled'
  | 'reauth_required'
  | 'interrupted';

export interface SyncJob {
  id: string;
  state: SyncState;
  /** `null` until the platform has said how many works there are. */
  total: number | null;
  processed: number;
  added: number;
  updated: number;
  skipped: number;
  missing: number;
  code: string | null;
  message: string | null;
  startedAt: string;
  finishedAt: string | null;
}

export interface SyncStatus {
  /** Only a complete sync sets this; an attempt's own time is on the job. */
  lastSyncedAt: string | null;
  job: SyncJob | null;
}

export type DownloadState =
  | 'queued'
  | 'resolving'
  | 'downloading'
  | 'verifying'
  | 'paused'
  | 'done'
  | 'failed'
  | 'cancelled'
  | 'reauth_required'
  | 'interrupted';

/** The service's record of one file. It never carries a download address. */
export interface DownloadTask {
  id: string;
  workId: string;
  title: string;
  part: number | null;
  partCount: number | null;
  state: DownloadState;
  bytesDone: number;
  /** `null` when the server does not say. Never shown as 0. */
  bytesTotal: number | null;
  fileName: string | null;
  code: string | null;
  message: string | null;
  canRetry: boolean;
  canResume: boolean;
  integrity: string | null;
  location: string | null;
  fileMissing: boolean;
  /** Measured on a running transfer; `null` until there is a sample. */
  bytesPerSecond: number | null;
  createdAt: string;
  finishedAt: string | null;
}

export interface DownloadUpdate {
  workId: string;
  title: string;
}

export interface DownloadList {
  tasks: DownloadTask[];
  activeCount: number;
  updates: DownloadUpdate[];
}

export interface UpdateSettings {
  autoCheck: boolean;
  lastCheckedAt: string | null;
}

export interface GalleryImage {
  url: string;
  width: number | null;
  height: number | null;
}

export interface WorkGalleryData {
  images: GalleryImage[];
  intro: string | null;
  unavailable: boolean;
}

export interface DownloadPlan {
  kind: 'direct' | 'split' | 'serial';
  parts: number[];
  totalBytes: number | null;
  folder: FolderInfo;
  freeBytes: number | null;
}

export type DownloadAction = 'cancel' | 'pause' | 'retry' | 'open-folder';

export type ExtractState =
  | 'queued'
  | 'checking'
  | 'extracting'
  | 'committing'
  | 'done'
  | 'not_needed'
  | 'failed'
  | 'cancelled'
  | 'interrupted';

export interface ExtractTask {
  id: string;
  workId: string;
  title: string;
  state: ExtractState;
  format: string | null;
  filesTotal: number | null;
  bytesTotal: number | null;
  bytesDone: number;
  code: string | null;
  message: string | null;
  canRetry: boolean;
  location: string | null;
  resultMissing: boolean;
  cleanupFailed: boolean;
  createdAt: string;
  finishedAt: string | null;
}

export interface ExtractionList {
  tasks: ExtractTask[];
  activeCount: number;
}

export type ExtractAction = 'cancel' | 'retry' | 'open-folder';

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

const dlsitePath = '/api/v1/sources/dlsite';
const folderPath = '/api/v1/settings/folders';
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

  async folders(signal?: AbortSignal): Promise<FolderInfo[]> {
    return (await apiGet<{ folders: FolderInfo[] }>(folderPath, undefined, signal)).folders;
  }

  async setFolder(kind: FolderInfo['kind'], path: string): Promise<FolderInfo[]> {
    return (await apiWrite<{ folders: FolderInfo[] }>('PUT', `${folderPath}/${kind}`, { path }))
      .folders;
  }

  async folderAction(kind: FolderInfo['kind'], action: 'pick' | 'open'): Promise<FolderInfo[]> {
    return (await apiWrite<{ folders: FolderInfo[] }>('POST', `${folderPath}/${kind}/${action}`))
      .folders;
  }

  gallery(workId: string, signal?: AbortSignal): Promise<WorkGalleryData> {
    return apiGet<WorkGalleryData>(`${workPath(workId)}/gallery`, undefined, signal);
  }

  updateSettings(signal?: AbortSignal): Promise<UpdateSettings> {
    return apiGet<UpdateSettings>('/api/v1/settings/updates', undefined, signal);
  }

  setUpdateSettings(autoCheck: boolean): Promise<UpdateSettings> {
    return apiWrite<UpdateSettings>('PUT', '/api/v1/settings/updates', { autoCheck });
  }

  downloads(signal?: AbortSignal): Promise<DownloadList> {
    return apiGet<DownloadList>('/api/v1/downloads', undefined, signal);
  }

  /** Spends the session on the platform, so only ever on the user's click. */
  downloadPlan(workId: string): Promise<DownloadPlan> {
    return apiWrite<DownloadPlan>('POST', `${workPath(workId)}/download-plan`);
  }

  createDownload(
    workId: string,
    parts: number[] | null,
    again: boolean,
    extract: boolean,
  ): Promise<DownloadList> {
    return apiWrite<DownloadList>('POST', '/api/v1/downloads', { workId, parts, again, extract });
  }

  extractions(signal?: AbortSignal): Promise<ExtractionList> {
    return apiGet<ExtractionList>('/api/v1/extractions', undefined, signal);
  }

  startExtraction(workId: string, again: boolean): Promise<ExtractionList> {
    return apiWrite<ExtractionList>('POST', '/api/v1/extractions', { workId, again });
  }

  extractionAction(id: string, action: ExtractAction): Promise<ExtractTask> {
    return apiWrite<ExtractTask>('POST', `/api/v1/extractions/${encodeURIComponent(id)}/${action}`);
  }

  clearExtractions(): Promise<ExtractionList> {
    return apiWrite<ExtractionList>('POST', '/api/v1/extractions/clear');
  }

  downloadAction(id: string, action: DownloadAction): Promise<DownloadTask> {
    return apiWrite<DownloadTask>('POST', `/api/v1/downloads/${encodeURIComponent(id)}/${action}`);
  }

  clearDownloads(): Promise<DownloadList> {
    return apiWrite<DownloadList>('POST', '/api/v1/downloads/clear');
  }

  syncStatus(signal?: AbortSignal): Promise<SyncStatus> {
    return apiGet<SyncStatus>(`${dlsitePath}/sync`, undefined, signal);
  }

  syncAction(action: 'sync' | 'sync/cancel'): Promise<SyncStatus> {
    return apiWrite<SyncStatus>('POST', `${dlsitePath}/${action}`);
  }

  dlsiteConnection(signal?: AbortSignal): Promise<DlsiteConnection> {
    return apiGet<DlsiteConnection>(`${dlsitePath}/connection`, undefined, signal);
  }

  /** The password is sent once in the request body and goes no further on this side. */
  dlsiteLogin(loginId: string, password: string, confirmSwitch: boolean, remember: boolean) {
    return apiWrite<DlsiteConnection>('POST', `${dlsitePath}/login`, {
      loginId,
      password,
      confirmSwitch,
      remember,
    });
  }

  dlsiteAction(
    action:
      | 'login/window'
      | 'login/saved'
      | 'login/cancel'
      | 'login/reveal'
      | 'saved-login/forget'
      | 'verify'
      | 'disconnect',
  ) {
    return apiWrite<DlsiteConnection>('POST', `${dlsitePath}/${action}`);
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
