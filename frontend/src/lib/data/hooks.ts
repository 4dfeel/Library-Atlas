import {
  keepPreviousData,
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError } from './api-client';
import type { DashboardResult, DashboardScope } from './dashboard';
import {
  realPageSize,
  realSource,
  type ConnectionStatus,
  type DlsiteConnection,
  type FolderInfo,
  type LibrarySummary,
  type SyncJob,
  type DownloadAction,
  type LocalCopy,
  type MediaBookmark,
  type Playlist,
  type PlaylistEntry,
  type ReaderBookmark,
  type WorkCollection,
  type SaveRule,
  type ScanItemState,
  type LocalCopyInput,
  type DownloadList,
  type DownloadState,
  type DownloadTask,
  type ExtractAction,
  type ExtractState,
  type ExtractTask,
  type SyncStatus,
} from './real-source';
import type { Game, GameDetail, GameUpdate, LibraryFilters } from './types';

const realRoot = ['library', 'real'] as const;

/** Pages that intersect the visible range. The first page also carries the summary. */
function pagesFor(start: number, end: number): number[] {
  const first = Math.floor(start / realPageSize);
  const last = Math.floor(Math.max(start, end - 1) / realPageSize);
  const pages = new Set([0]);
  for (let page = first; page <= last; page++) pages.add(page);
  return [...pages];
}

export interface LibraryCollection {
  summary: LibrarySummary | undefined;
  count: number;
  /** `undefined` while that row's page has not arrived; the grid shows a placeholder. */
  gameAt: (index: number) => Game | undefined;
  onVisibleRange: (start: number, end: number) => void;
  isPending: boolean;
  isFetching: boolean;
  /** Nothing to show at all. Failed refreshes of data on screen are `isStale` instead. */
  error: Error | null;
  /** A later page could not be read, or a refresh failed while older data stays visible. */
  isStale: boolean;
  refetch: () => void;
}

/**
 * Reads only the pages the virtualizer is showing, so large libraries are never sent or
 * rendered in one piece.
 */
export function useLibraryCollection(filters: LibraryFilters): LibraryCollection {
  const [range, setRange] = useState({ start: 0, end: realPageSize });
  const pages = pagesFor(range.start, range.end);
  const real = useQueries({
    queries: pages.map((page) => ({
      queryKey: [...realRoot, 'works', filters, page] as const,
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        realSource.listPage(filters, page * realPageSize, realPageSize, signal),
      staleTime: 60_000,
      gcTime: 120_000,
      retry: false,
      // Keep the old results on screen, marked as updating, while new filters load.
      placeholderData: page === 0 ? keepPreviousData : undefined,
    })),
  });
  const onVisibleRange = useCallback((start: number, end: number) => {
    setRange((current) =>
      current.start === start && current.end === end ? current : { start, end },
    );
  }, []);

  const [lastSummary, setLastSummary] = useState<LibrarySummary | undefined>();
  const firstPage = real[0]?.data;
  if (firstPage && firstPage !== lastSummary) setLastSummary(firstPage);
  const realItems = new Map<number, Game[]>();
  pages.forEach((page, position) => {
    const data = real[position]?.data;
    if (data) realItems.set(page, data.items);
  });
  const realGameAt = (index: number) =>
    realItems.get(Math.floor(index / realPageSize))?.[index % realPageSize];

  const first = real[0]!;
  return {
    // While new filters load, keep the last numbers: a flash of "0" would read as a result.
    summary: first.data ?? (first.isPending ? lastSummary : undefined),
    count: first.data?.filteredCount ?? 0,
    gameAt: realGameAt,
    onVisibleRange,
    isPending: first.isPending,
    isFetching: real.some((query) => query.isFetching),
    error: first.data ? null : first.error,
    isStale: real.some((query) => query.isError),
    refetch: () => real.forEach((query) => void query.refetch()),
  };
}

function detailKey(id: string) {
  return [...realRoot, 'detail', id] as const;
}

/** One record by stable ID; private and absent IDs fail identically. */
export function useGameDetail(id: string) {
  return useQuery({
    queryKey: detailKey(id),
    queryFn: ({ signal }) => realSource.getGame({ id, signal }),
    staleTime: 60_000,
    gcTime: 120_000,
    retry: false,
  });
}

/**
 * Writes one game's personal fields. Each caller owns its pending/error state, so a
 * failed note save does not mask a successful rating change. The shared scope saves one
 * work's edits strictly in order; a response can then never overwrite a newer one.
 */
export function useUpdateGame(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: [...realRoot, 'update', id],
    scope: { id: `work:${id}` },
    mutationFn: (update: GameUpdate) => realSource.updateGame(id, update),
    onSuccess: (detail: GameDetail) => {
      queryClient.setQueryData<GameDetail>(detailKey(id), (cached) =>
        cached?.version !== undefined &&
        detail.version !== undefined &&
        cached.version > detail.version
          ? cached
          : detail,
      );
      // List facets and other cached details may change.
      return queryClient.invalidateQueries({ queryKey: realRoot });
    },
    onError: () => queryClient.invalidateQueries({ queryKey: realRoot }),
  });
}

/** Favorites persist with the other personal fields. */
export function useToggleFavorite() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => realSource.toggleFavorite(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: realRoot }),
  });
}

export function useDashboard(scope: DashboardScope, batch = 0) {
  return useQuery<DashboardResult>({
    queryKey: [...realRoot, 'dashboard', scope, batch],
    queryFn: ({ signal }) => realSource.dashboard({ scope, batch, signal }),
    staleTime: 60_000,
    gcTime: 120_000,
    retry: false,
    // Keep the previous range on screen while a new range aggregates.
    placeholderData: (previous) => previous,
  });
}

/** Connection states as the local service reports them. */
export function useRealSources(enabled = true) {
  return useQuery({
    enabled,
    queryKey: [...realRoot, 'sources'],
    queryFn: ({ signal }) => realSource.sources(signal),
    staleTime: 60_000,
    gcTime: 120_000,
    retry: false,
  });
}

const inProgress = new Set<ConnectionStatus>(['authenticating', 'needs_verification', 'verifying']);

/**
 * The real DLsite connection. Login goes around useMutation on purpose: mutation state
 * keeps its variables, and the password must not stay in any cache.
 */
export function useDlsiteConnection(enabled = true) {
  const queryClient = useQueryClient();
  const key = [...realRoot, 'dlsite-connection'];
  const query = useQuery({
    enabled,
    queryKey: key,
    queryFn: ({ signal }) => realSource.dlsiteConnection(signal),
    retry: false,
    // Only while something is happening; this asks the local service, not the platform.
    refetchInterval: (current) =>
      current.state.data && inProgress.has(current.state.data.state) ? 700 : 5_000,
  });
  // A login finishes in the background, so badges follow the state rather than the click.
  const currentState = query.data?.state;
  useEffect(() => {
    if (currentState) void queryClient.invalidateQueries({ queryKey: [...realRoot, 'sources'] });
  }, [currentState, queryClient]);
  const settle = async (connection: DlsiteConnection) => {
    // A poll that started before this action must not land after it and restore old state.
    await queryClient.cancelQueries({ queryKey: key });
    queryClient.setQueryData(key, connection);
    return connection;
  };
  return {
    connection: query.data,
    isError: query.isError && !query.data,
    actions: {
      login: async (loginId: string, password: string, confirmSwitch: boolean, remember: boolean) =>
        settle(await realSource.dlsiteLogin(loginId, password, confirmSwitch, remember)),
      loginWithSaved: async () => settle(await realSource.dlsiteAction('login/saved')),
      forgetSaved: async () => settle(await realSource.dlsiteAction('saved-login/forget')),
      loginWithWindow: async () => settle(await realSource.dlsiteAction('login/window')),
      cancel: async () => settle(await realSource.dlsiteAction('login/cancel')),
      reveal: async () => settle(await realSource.dlsiteAction('login/reveal')),
      verify: async () => settle(await realSource.dlsiteAction('verify')),
      disconnect: async () => settle(await realSource.dlsiteAction('disconnect')),
    },
  };
}

const syncActive = new Set<SyncJob['state']>(['preparing', 'reading', 'saving']);

export function isSyncActive(job: SyncJob): boolean {
  return syncActive.has(job.state);
}

/**
 * Sync progress as the service reports it. Lists and counts refresh every few seconds while
 * works arrive and once at the end, never on each one, so pages do not flicker.
 */
export function useDlsiteSync() {
  const queryClient = useQueryClient();
  const key = [...realRoot, 'dlsite-sync'];
  const [error, setError] = useState<string | null>(null);
  const query = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => realSource.syncStatus(signal),
    retry: false,
    refetchInterval: (current) => {
      const job = current.state.data?.job;
      return job && isSyncActive(job) ? 1_000 : 15_000;
    },
  });
  const job = query.data?.job;
  const state = job?.state;
  const processed = job?.processed;
  const lastRefresh = useRef(0);
  useEffect(() => {
    if (!state) return;
    const running = syncActive.has(state);
    if (running && Date.now() - lastRefresh.current < 4_000) return;
    lastRefresh.current = Date.now();
    for (const part of ['works', 'dashboard', 'sources', 'detail', 'dlsite-connection'])
      void queryClient.invalidateQueries({ queryKey: [...realRoot, part] });
  }, [state, processed, queryClient]);
  const act = (action: 'sync' | 'sync/cancel') => async () => {
    setError(null);
    try {
      const next: SyncStatus = await realSource.syncAction(action);
      await queryClient.cancelQueries({ queryKey: key });
      queryClient.setQueryData(key, next);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '操作没有完成，请重试。');
    }
  };
  return {
    status: query.data,
    error,
    start: () => void act('sync')(),
    cancel: () => void act('sync/cancel')(),
  };
}

const foldersKey = [...realRoot, 'folders'];

export function useFolders() {
  return useQuery({
    queryKey: foldersKey,
    queryFn: ({ signal }) => realSource.folders(signal),
    staleTime: 10_000,
    retry: false,
  });
}

export function useFolderActions(kind: FolderInfo['kind']) {
  const queryClient = useQueryClient();
  const onSuccess = (folders: FolderInfo[]) => queryClient.setQueryData(foldersKey, folders);
  return {
    pick: useMutation({ mutationFn: () => realSource.folderAction(kind, 'pick'), onSuccess }),
    open: useMutation({ mutationFn: () => realSource.folderAction(kind, 'open'), onSuccess }),
    save: useMutation({
      mutationFn: (path: string) => realSource.setFolder(kind, path),
      onSuccess,
    }),
  };
}

/** Service state for the current session; polled while real mode is showing. */
export function useServiceReady() {
  return useQuery({
    queryKey: ['service', 'ready'],
    queryFn: ({ signal }) => realSource.ready(signal),
    staleTime: 5_000,
    gcTime: 60_000,
    retry: false,
    refetchInterval: 15_000,
  });
}

export interface Workspace {
  /** Running on the isolated synthetic library; always labelled as such. */
  isTestLibrary: boolean;
  serviceDown: boolean;
  serviceMessage: string | null;
  retryService: () => void;
}

export function useWorkspace(): Workspace {
  const ready = useServiceReady();
  const queryClient = useQueryClient();
  return {
    isTestLibrary: ready.data?.profile === 'test',
    serviceDown: ready.isError || ready.data?.status === 'not_ready',
    serviceMessage: ready.data?.status === 'not_ready' ? (ready.data.message ?? null) : null,
    retryService: () => {
      void ready.refetch();
      void queryClient.invalidateQueries({ queryKey: realRoot });
    },
  };
}

export function isAccountMismatch(error: unknown): boolean {
  return error instanceof ApiError && error.code === 'account_mismatch';
}

export function isConflict(error: unknown): boolean {
  return error instanceof ApiError && error.code === 'version_conflict';
}

const downloadsActive = new Set<DownloadState>([
  'queued',
  'resolving',
  'downloading',
  'verifying',
  'paused',
]);

export function isDownloadActive(task: Pick<DownloadTask, 'state'>) {
  return downloadsActive.has(task.state);
}

const downloadsKey = [...realRoot, 'downloads'];
const emptyUpdates: DownloadList['updates'] = [];

/**
 * The service's queue. It is read here and never computed here, so it
 * is the same on every page and after a reload. Progress refreshes this query alone; only
 * a finished download touches the library's own data, so lists keep their place.
 */
export function useDownloads() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: downloadsKey,
    queryFn: ({ signal }) => realSource.downloads(signal),
    retry: false,
    refetchInterval: (current) => (current.state.data?.activeCount ? 1_000 : 15_000),
  });
  const tasks = useMemo(() => query.data?.tasks ?? [], [query.data]);
  const finished = tasks.filter((task) => task.state === 'done' && !task.fileMissing).length;
  const lastFinished = useRef<number | null>(null);
  useEffect(() => {
    if (lastFinished.current !== null && lastFinished.current !== finished)
      for (const part of ['works', 'dashboard', 'detail'])
        void queryClient.invalidateQueries({ queryKey: [...realRoot, part] });
    lastFinished.current = finished;
  }, [finished, queryClient]);
  return {
    tasks,
    updates: query.data?.updates ?? emptyUpdates,
    activeCount: query.data?.activeCount ?? 0,
    failed: query.isError,
  };
}

export function useDownloadActions() {
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: downloadsKey });
  return {
    plan: (workId: string) => realSource.downloadPlan(workId),
    create: async (workId: string, parts: number[] | null, again: boolean, extract: boolean) => {
      await realSource.createDownload(workId, parts, again, extract);
      await refresh();
    },
    act: async (id: string, action: DownloadAction) => {
      await realSource.downloadAction(id, action);
      await refresh();
    },
    clear: async () => {
      await realSource.clearDownloads();
      await refresh();
    },
  };
}

const extractActive = new Set<ExtractState>(['queued', 'checking', 'extracting', 'committing']);

export function isExtractActive(task: Pick<ExtractTask, 'state'>) {
  return extractActive.has(task.state);
}

const extractionsKey = [...realRoot, 'extractions'];

/**
 * The service's unpacking tasks, in real mode only. It stays awake while downloads run too:
 * a download the user asked to unpack moves on to this queue without any further request.
 */
export function useExtractions() {
  const query = useQuery({
    queryKey: extractionsKey,
    queryFn: ({ signal }) => realSource.extractions(signal),
    retry: false,
    refetchInterval: (current) => {
      const downloads = current.state.data?.activeCount ?? 0;
      return downloads ? 1_000 : 3_000;
    },
  });
  return {
    tasks: useMemo(() => query.data?.tasks ?? [], [query.data]),
    activeCount: query.data?.activeCount ?? 0,
  };
}

export function useExtractionActions() {
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: extractionsKey });
  return {
    start: async (workId: string, again: boolean) => {
      await realSource.startExtraction(workId, again);
      await refresh();
    },
    act: async (id: string, action: ExtractAction) => {
      await realSource.extractionAction(id, action);
      await refresh();
    },
    clear: async () => {
      await realSource.clearExtractions();
      await refresh();
    },
  };
}

export function useUpdateSettings() {
  const queryClient = useQueryClient();
  const key = [...realRoot, 'update-settings'];
  const query = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => realSource.updateSettings(signal),
    retry: false,
  });
  return {
    settings: query.data,
    setAuto: (enabled: boolean) => {
      void realSource
        .setUpdateSettings(enabled)
        .then((next) => queryClient.setQueryData(key, next))
        .catch(() => queryClient.invalidateQueries({ queryKey: key }));
    },
  };
}

/** Real works only; a work's page asks once, and the service keeps the list for a week. */
export function useWorkGallery(workId: string) {
  const query = useQuery({
    queryKey: [...realRoot, 'gallery', workId],
    queryFn: ({ signal }) => realSource.gallery(workId, signal),
    retry: false,
    staleTime: 3_600_000,
  });
  return { gallery: query.data, loading: query.isPending };
}

/** Asked once a work's page is open, and never while browsing the library. */
export function useWorkIntroduction(workId: string) {
  const queryClient = useQueryClient();
  const key = [...realRoot, 'introduction', workId];
  const query = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => realSource.introduction(workId, signal),
    retry: false,
    staleTime: 3_600_000,
  });
  const [refreshing, setRefreshing] = useState(false);
  return {
    intro: query.data,
    loading: query.isPending,
    refreshing,
    refresh: () => {
      setRefreshing(true);
      void realSource
        .refreshIntroduction(workId)
        .then((next) => queryClient.setQueryData(key, next))
        .catch(() => undefined)
        .finally(() => setRefreshing(false));
    },
  };
}

export function useLocalCopies(workId: string) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: [...realRoot, 'local-copies', workId],
    queryFn: ({ signal }) => realSource.localCopies(workId, signal),
    retry: false,
    // A drive coming back, or a folder moved outside Atlas, shows up without a reload.
    refetchInterval: 30_000,
  });
  return {
    copies: query.data ?? emptyCopies,
    loading: query.isPending,
    refresh: useCallback(
      () => queryClient.invalidateQueries({ queryKey: [...realRoot, 'local-copies', workId] }),
      [queryClient, workId],
    ),
  };
}

const emptyCopies: LocalCopy[] = [];

export function useLocalCopyActions(workId: string) {
  const queryClient = useQueryClient();
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: [...realRoot, 'local-copies', workId] });
  const then = async <T>(work: Promise<T>) => {
    const result = await work;
    await refresh();
    return result;
  };
  return {
    preview: (path: string) => realSource.previewLocalCopy(workId, path),
    chooseFolder: async () => (await realSource.chooseCopyFolder()).path,
    add: (body: LocalCopyInput) => then(realSource.addLocalCopy(workId, body)),
    update: (id: string, body: Partial<LocalCopyInput>) =>
      then(realSource.updateLocalCopy(id, body)),
    remove: (id: string) => then(realSource.removeLocalCopy(id)),
    setDefault: (id: string) => then(realSource.localCopyAction(id, 'default')),
    open: (id: string) => realSource.localCopyAction(id, 'open'),
    launch: (id: string) =>
      realSource.launchLocalCopy(id).then(async (result) => {
        await queryClient.invalidateQueries({ queryKey: [...realRoot, 'work-play', workId] });
        return result;
      }),
  };
}

const scanKey = [...realRoot, 'library-scan'];

export function useLibraryScan() {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const query = useQuery({
    queryKey: scanKey,
    queryFn: ({ signal }) => realSource.scanStatus(signal),
    retry: false,
    refetchInterval: (current) => (current.state.data?.job?.state === 'running' ? 1_000 : false),
  });
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: scanKey }),
      queryClient.invalidateQueries({ queryKey: [...realRoot, 'local-copies'] }),
    ]);
  const run = <T>(work: Promise<T>) =>
    work
      .then(async (result) => {
        setError(null);
        await refresh();
        return result;
      })
      .catch((failure: unknown) => {
        setError(failure instanceof Error ? failure.message : '操作没有完成，请重试。');
        throw failure;
      });
  return {
    status: query.data,
    error,
    start: (drives: string[], roots: string[], deep: boolean) =>
      void run(realSource.scanStart(drives, roots, deep)).catch(() => undefined),
    cancel: () => void run(realSource.scanCancel()).catch(() => undefined),
    importMatches: (includeLikely: boolean) => run(realSource.scanImport(includeLikely)),
    undo: (batchId: string) => void run(realSource.scanUndo(batchId)).catch(() => undefined),
    link: (itemId: string, workId: string) =>
      void run(realSource.scanLink(itemId, workId)).catch(() => undefined),
    ignore: (itemId: string) => void run(realSource.scanIgnore(itemId)).catch(() => undefined),
  };
}

export function useLibraryScanItems(state: ScanItemState, offset: number, limit: number) {
  const query = useQuery({
    queryKey: [...scanKey, 'items', state, offset, limit],
    queryFn: ({ signal }) => realSource.scanItems(state, offset, limit, signal),
    placeholderData: (previous) => previous,
    retry: false,
  });
  return { items: query.data?.items ?? [], total: query.data?.total ?? 0 };
}

const updateWorking = new Set([
  'queued',
  'backing_up',
  'downloading',
  'unpacking',
  'replacing',
  'cleaning',
]);

export function useGameUpdate(workId: string) {
  const queryClient = useQueryClient();
  const key = [...realRoot, 'game-update', workId];
  const [error, setError] = useState<string | null>(null);
  const query = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => realSource.gameUpdate(workId, signal),
    retry: false,
    refetchInterval: (current) =>
      updateWorking.has(current.state.data?.task?.state ?? '') ? 1_000 : false,
  });
  const run = <T>(work: Promise<T>) =>
    work
      .then(async (result) => {
        setError(null);
        await queryClient.invalidateQueries({ queryKey: key });
        await queryClient.invalidateQueries({ queryKey: [...realRoot, 'local-copies', workId] });
        return result;
      })
      .catch((failure: unknown) => {
        setError(failure instanceof Error ? failure.message : '操作没有完成，请重试。');
        throw failure;
      });
  const act = (id: string, action: 'confirm' | 'rollback' | 'retry' | 'cancel') =>
    void run(realSource.gameUpdateAction(id, action)).catch(() => undefined);
  return {
    status: query.data,
    error,
    saveConfig: (rules: SaveRule[], none: boolean) =>
      run(realSource.saveConfig(workId, rules, none)),
    start: (copyId: string) => run(realSource.startGameUpdate(workId, copyId)),
    confirm: (id: string) => act(id, 'confirm'),
    rollback: (id: string) => act(id, 'rollback'),
    retry: (id: string) => act(id, 'retry'),
    restore: (backupId: string, copyId: string) =>
      void run(realSource.restoreSaves(backupId, copyId)).catch(() => undefined),
  };
}

export function useAudioTracks(workId: string) {
  const query = useQuery({
    queryKey: [...realRoot, 'audio', workId],
    queryFn: ({ signal }) => realSource.audio(workId, signal),
    retry: false,
  });
  return { audio: query.data, loading: query.isPending };
}

export function useAudioBookmarks(workId: string) {
  const query = useQuery({
    queryKey: [...realRoot, 'audio-bookmarks', workId],
    queryFn: ({ signal }) => realSource.audioBookmarks(workId, signal),
    retry: false,
  });
  return { bookmarks: query.data ?? emptyBookmarks };
}

const emptyBookmarks: MediaBookmark[] = [];

export function useBookmarkActions(workId: string) {
  const queryClient = useQueryClient();
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: [...realRoot, 'audio-bookmarks', workId] });
  return {
    add: async (copyId: string, resourceId: string, position: number) => {
      await realSource.addAudioBookmark(copyId, resourceId, position);
      await refresh();
    },
    remove: async (id: string) => {
      await realSource.removeAudioBookmark(id);
      await refresh();
    },
  };
}

export function usePlaylists() {
  const queryClient = useQueryClient();
  const key = [...realRoot, 'playlists'];
  const query = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => realSource.playlists(signal),
    retry: false,
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: key });
  return {
    playlists: query.data ?? emptyPlaylists,
    save: async (name: string, items: PlaylistEntry[]) => {
      await realSource.savePlaylist(name, items);
      await refresh();
    },
    remove: async (id: string) => {
      await realSource.removePlaylist(id);
      await refresh();
    },
  };
}

const emptyPlaylists: Playlist[] = [];

export function useBooks(workId: string) {
  const queryClient = useQueryClient();
  const key = [...realRoot, 'books', workId];
  const query = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => realSource.books(workId, signal),
    retry: false,
  });
  return {
    books: query.data,
    loading: query.isPending,
    refresh: () => queryClient.invalidateQueries({ queryKey: key }),
  };
}

export function useBookPages(copyId: string, bookId: string) {
  const query = useQuery({
    // Read once per opening: the saved place must not move under the reader's feet.
    queryKey: [...realRoot, 'book-pages', copyId, bookId],
    queryFn: ({ signal }) => realSource.bookPages(copyId, bookId, signal),
    gcTime: 0,
    staleTime: Infinity,
    retry: false,
  });
  return {
    data: query.data,
    error: query.error ? (query.error as Error).message : null,
    retry: () => void query.refetch(),
  };
}

export function useReaderBookmarks(copyId: string, bookId: string) {
  const query = useQuery({
    queryKey: [...realRoot, 'reader-bookmarks', bookId],
    queryFn: ({ signal }) => realSource.readerBookmarks(copyId, bookId, signal),
    retry: false,
  });
  return { bookmarks: query.data ?? emptyReaderBookmarks };
}

const emptyReaderBookmarks: ReaderBookmark[] = [];

export function useReaderActions(copyId: string, bookId: string) {
  const queryClient = useQueryClient();
  return useMemo(() => {
    const refresh = () =>
      queryClient.invalidateQueries({ queryKey: [...realRoot, 'reader-bookmarks', bookId] });
    return {
      savePosition: (pageId: string, pageIndex: number, pageCount: number, finished: boolean) =>
        void realSource
          .saveReading({ copyId, bookId, pageId, pageIndex, pageCount, finished })
          .catch(() => undefined),
      setRead: (read: boolean) => realSource.saveReadState(copyId, bookId, read),
      addBookmark: async (pageId: string, pageIndex: number) => {
        await realSource.addReaderBookmark(copyId, bookId, pageId, pageIndex);
        await refresh();
      },
      removeBookmark: async (id: string) => {
        await realSource.removeReaderBookmark(id);
        await refresh();
      },
    };
  }, [bookId, copyId, queryClient]);
}

export function useCollections(workId?: string) {
  const query = useQuery({
    queryKey: [...realRoot, 'collections', workId ?? null],
    queryFn: ({ signal }) => realSource.collections(workId, signal),
    retry: false,
  });
  return {
    collections: query.data?.collections ?? emptyCollections,
    favorites: query.data?.favorites ?? 0,
    loading: query.isPending,
  };
}

const emptyCollections: WorkCollection[] = [];

/** Everything shown from a collection can change with it, so the library is read again too. */
export function useCollectionActions(workId?: string) {
  const queryClient = useQueryClient();
  const then = async (work: Promise<unknown>) => {
    await work;
    await queryClient.invalidateQueries({ queryKey: realRoot });
  };
  return {
    create: (name: string) => then(realSource.createCollection(name, workId)),
    rename: (id: string, name: string) => then(realSource.renameCollection(id, name)),
    remove: (id: string) => then(realSource.removeCollection(id)),
    toggle: (id: string, inside: boolean) =>
      workId ? then(realSource.setInCollection(id, workId, inside)) : Promise.resolve(),
  };
}

export function useWorkActions(workId: string) {
  const queryClient = useQueryClient();
  void workId;
  return {
    launch: (copyId: string) =>
      realSource.launchLocalCopy(copyId).then(async (result) => {
        await queryClient.invalidateQueries({ queryKey: realRoot });
        return result;
      }),
    shortcut: (copyId: string) => realSource.addShortcut(copyId),
    browse: (copyId: string) => realSource.localCopyAction(copyId, 'open'),
  };
}

export function useUninstall(copyId: string) {
  const queryClient = useQueryClient();
  const query = useQuery({
    // Checked fresh each time: what may be removed depends on the moment.
    queryKey: [...realRoot, 'uninstall', copyId],
    queryFn: ({ signal }) => realSource.uninstallPreview(copyId, signal),
    gcTime: 0,
    staleTime: 0,
    retry: false,
  });
  return {
    preview: query.data,
    error: query.error ? (query.error as Error).message : null,
    uninstall: async (root: string) => {
      await realSource.uninstall(copyId, root);
      await queryClient.invalidateQueries({ queryKey: realRoot });
    },
  };
}

/** For choosing a work by hand. Goes through the same ordinary list as everything else. */
export function useWorkSearch(search: string) {
  const query = useQuery({
    queryKey: [...realRoot, 'work-search', search],
    queryFn: ({ signal }) => realSource.searchWorks(search, signal),
    retry: false,
    placeholderData: (previous) => previous,
  });
  return { works: query.data ?? [], loading: query.isPending };
}

export function useCloudStatus() {
  const queryClient = useQueryClient();
  const key = [...realRoot, 'cloud'];
  const [error, setError] = useState<string | null>(null);
  const query = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => realSource.cloudStatus(signal),
    retry: false,
    refetchInterval: (current) => (current.state.data?.connecting ? 1_000 : false),
  });
  const run = async (work: Promise<unknown>) => {
    try {
      await work;
      setError(null);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '操作没有完成，请重试。');
    }
    await queryClient.invalidateQueries({ queryKey: realRoot });
  };
  return {
    status: query.data,
    error,
    actions: {
      connect: (client: { clientId: string; clientSecret: string } | null) =>
        run(
          (async () => {
            if (client) await realSource.setCloudClient(client.clientId, client.clientSecret);
            await realSource.cloudConnect();
          })(),
        ),
      disconnect: () => run(realSource.cloudDisconnect()),
      options: (autoCheck: boolean, autoBackup: boolean) =>
        run(realSource.setCloudOptions(autoCheck, autoBackup)),
    },
  };
}

export function useWorkCloud(workId: string) {
  const queryClient = useQueryClient();
  const key = [...realRoot, 'work-cloud', workId];
  const [error, setError] = useState<string | null>(null);
  const query = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => realSource.workCloud(workId, signal),
    retry: false,
    refetchInterval: (current) =>
      current.state.data && current.state.data.queue.count > 0 ? 2_000 : false,
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: key });
  const run = async (work: Promise<unknown>) => {
    try {
      await work;
      setError(null);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '操作没有完成，请重试。');
      throw failure;
    } finally {
      await refresh();
    }
  };
  return {
    cloud: query.data,
    error,
    actions: {
      refresh,
      backup: () => run(realSource.workCloudAction(workId, 'backup')),
      retry: () => run(realSource.workCloudAction(workId, 'retry')).catch(() => undefined),
      restore: (snapshotId: string) => run(realSource.workCloudRestore(workId, snapshotId)),
      resolve: (keep: string) => run(realSource.workCloudResolve(workId, keep)),
    },
  };
}

export function useSaveSuggestions(workId: string) {
  const queryClient = useQueryClient();
  const key = [...realRoot, 'save-suggestions', workId];
  const [error, setError] = useState<string | null>(null);
  const query = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => realSource.saveSuggestions(workId, signal),
    retry: false,
    refetchInterval: (current) => {
      const state = current.state.data?.session.state;
      // A launch from Atlas ends by itself: keep the list current while that is going on.
      return state === 'scanning' ? 1_000 : state === 'recording' ? 5_000 : false;
    },
  });
  const run = async (finish: boolean) => {
    try {
      await realSource.saveSession(workId, finish);
      setError(null);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '操作没有完成，请重试。');
    }
    await queryClient.invalidateQueries({ queryKey: key });
  };
  return {
    data: query.data,
    error,
    actions: { start: () => run(false), finish: () => run(true) },
  };
}

export function usePlayStats() {
  const query = useQuery({
    queryKey: [...realRoot, 'play-stats'],
    queryFn: ({ signal }) => realSource.playStats(signal),
    retry: false,
  });
  return {
    stats: query.data,
    loading: query.isPending,
    error: query.error ? (query.error as Error).message : null,
  };
}

export function useWorkPlay(workId: string) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: [...realRoot, 'work-play', workId],
    queryFn: ({ signal }) => realSource.workPlay(workId, signal),
    retry: false,
    refetchInterval: (current) => (current.state.data?.running ? 3_000 : false),
  });
  // A game that just ended changed the totals shown all over the page.
  const running = query.data?.running;
  const wasRunning = useRef(false);
  useEffect(() => {
    if (wasRunning.current && running === false)
      void queryClient.invalidateQueries({ queryKey: realRoot });
    wasRunning.current = Boolean(running);
  }, [queryClient, running]);
  return { play: query.data };
}
