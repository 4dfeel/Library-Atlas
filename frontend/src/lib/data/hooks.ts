import {
  keepPreviousData,
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { useCallback, useEffect, useState, useSyncExternalStore } from 'react';
import { ApiError } from './api-client';
import type { DashboardResult, DashboardScope } from './dashboard';
import type { Connections } from './demo-connections';
import { demoConnections, demoTasks, onDemoTaskComplete } from './demo-runtime';
import type { DemoTask } from './demo-tasks';
import { getDemoSource } from './demo-source';
import {
  realPageSize,
  realSource,
  type ConnectionStatus,
  type DlsiteConnection,
  type FolderInfo,
  type LibrarySummary,
} from './real-source';
import type { DemoScenario, DemoSize, Game, GameDetail, GameUpdate, LibraryFilters } from './types';
import { useWorkspaceMode, type WorkspaceMode } from './workspace';

export interface LibraryOptions {
  size: DemoSize;
  scenario?: DemoScenario;
}

// Every cached value lives under its mode, so one mode can never render the other's data.
const demoRoot = ['library', 'demo'] as const;
const realRoot = ['library', 'real'] as const;
const noTasks: readonly DemoTask[] = [];

export function workspaceRoot(mode: WorkspaceMode) {
  return mode === 'demo' ? demoRoot : realRoot;
}

function useLibrary(
  filters: LibraryFilters,
  { size, scenario = 'normal', enabled }: LibraryOptions & { enabled: boolean },
) {
  return useQuery({
    enabled,
    queryKey: [...demoRoot, size, 'ordinary', scenario, filters],
    queryFn: ({ signal }) => getDemoSource(size).list({ filters, scenario, signal }),
    staleTime: 60_000,
    gcTime: 120_000,
    retry: false,
  });
}

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
 * One list view for both modes. Demo holds its whole synthetic array in memory; real
 * reads only the pages the virtualizer is showing, so large libraries are never sent
 * or rendered in one piece.
 */
export function useLibraryCollection(
  filters: LibraryFilters,
  { size, scenario }: LibraryOptions,
): LibraryCollection {
  const mode = useWorkspaceMode();
  const demo = useLibrary(filters, { size, scenario, enabled: mode === 'demo' });
  const [range, setRange] = useState({ start: 0, end: realPageSize });
  const pages = pagesFor(range.start, range.end);
  const real = useQueries({
    queries: pages.map((page) => ({
      enabled: mode === 'real',
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

  const demoData = demo.data;
  const realItems = new Map<number, Game[]>();
  pages.forEach((page, position) => {
    const data = real[position]?.data;
    if (data) realItems.set(page, data.items);
  });
  const realGameAt = (index: number) =>
    realItems.get(Math.floor(index / realPageSize))?.[index % realPageSize];
  const demoGameAt = useCallback((index: number) => demoData?.items[index], [demoData]);

  if (mode === 'demo')
    return {
      summary: demoData,
      count: demoData?.items.length ?? 0,
      gameAt: demoGameAt,
      onVisibleRange,
      isPending: demo.isPending,
      isFetching: demo.isFetching,
      error: demo.error,
      isStale: false,
      refetch: () => void demo.refetch(),
    };

  const first = real[0]!;
  return {
    summary: first.data,
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

function detailKey(
  mode: WorkspaceMode,
  size: DemoSize,
  id: string,
  scenario: DemoScenario = 'normal',
) {
  return mode === 'demo'
    ? ([...demoRoot, size, 'ordinary-detail', id, scenario] as const)
    : ([...realRoot, 'detail', id] as const);
}

/** One record by stable ID; private and absent IDs fail identically. */
export function useGameDetail(id: string, { size, scenario = 'normal' }: LibraryOptions) {
  const mode = useWorkspaceMode();
  return useQuery({
    queryKey: detailKey(mode, size, id, scenario),
    queryFn: ({ signal }) =>
      mode === 'demo'
        ? getDemoSource(size).getGame({ id, scenario, signal })
        : realSource.getGame({ id, signal }),
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
export function useUpdateGame(size: DemoSize, id: string) {
  const queryClient = useQueryClient();
  const mode = useWorkspaceMode();
  const root = workspaceRoot(mode);
  return useMutation({
    mutationKey: [...root, 'update', id],
    scope: { id: `${mode}:work:${id}` },
    mutationFn: (update: GameUpdate) =>
      mode === 'demo'
        ? getDemoSource(size).updateGame(id, update)
        : realSource.updateGame(id, update),
    onSuccess: (detail: GameDetail) => {
      queryClient.setQueryData<GameDetail>(detailKey(mode, size, id), (cached) =>
        cached?.version !== undefined &&
        detail.version !== undefined &&
        cached.version > detail.version
          ? cached
          : detail,
      );
      // Both scales share one store; list facets and other cached details may change.
      return queryClient.invalidateQueries({ queryKey: root });
    },
    onError: () => queryClient.invalidateQueries({ queryKey: root }),
  });
}

/** Favorites persist with the other personal fields of the current mode. */
export function useToggleFavorite(size: DemoSize) {
  const queryClient = useQueryClient();
  const mode = useWorkspaceMode();
  const root = workspaceRoot(mode);
  return useMutation({
    mutationFn: (id: string) =>
      mode === 'demo' ? getDemoSource(size).toggleFavorite(id) : realSource.toggleFavorite(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: root }),
  });
}

export function useResetDemoEdits(size: DemoSize) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await getDemoSource(size).resetEdits();
      demoTasks.dispose();
      demoConnections.reset();
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: demoRoot }),
  });
}

export function getDemoEditCount(size: DemoSize): number {
  return getDemoSource(size).editedCount();
}

export function useDashboard(
  scope: DashboardScope,
  {
    size,
    scenario = 'normal',
    batch = 0,
    enabled = true,
  }: LibraryOptions & { batch?: number; enabled?: boolean },
) {
  const mode = useWorkspaceMode();
  return useQuery<DashboardResult>({
    enabled,
    queryKey:
      mode === 'demo'
        ? [...demoRoot, size, 'ordinary-dashboard', scope, batch, scenario]
        : [...realRoot, 'dashboard', scope, batch],
    queryFn: ({ signal }) =>
      mode === 'demo'
        ? getDemoSource(size).dashboard({ scope, batch, scenario, signal })
        : realSource.dashboard({ scope, batch, signal }),
    staleTime: 60_000,
    gcTime: 120_000,
    retry: false,
    // Keep the previous range on screen while a new range aggregates.
    placeholderData: (previous) => previous,
  });
}

/** Demo only: demo sessions are never read by real-mode views. */
export function useConnections(): Connections {
  return useSyncExternalStore(demoConnections.subscribe, demoConnections.getSnapshot);
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
      current.state.data && inProgress.has(current.state.data.state) ? 700 : 30_000,
  });
  // A login finishes in the background, so badges follow the state rather than the click.
  const currentState = query.data?.state;
  useEffect(() => {
    if (currentState) void queryClient.invalidateQueries({ queryKey: [...realRoot, 'sources'] });
  }, [currentState, queryClient]);
  const settle = (connection: DlsiteConnection) => {
    queryClient.setQueryData(key, connection);
    return connection;
  };
  return {
    connection: query.data,
    isError: query.isError && !query.data,
    actions: {
      login: async (loginId: string, password: string, confirmSwitch: boolean) =>
        settle(await realSource.dlsiteLogin(loginId, password, confirmSwitch)),
      loginWithWindow: async () => settle(await realSource.dlsiteAction('login/window')),
      cancel: async () => settle(await realSource.dlsiteAction('login/cancel')),
      reveal: async () => settle(await realSource.dlsiteAction('login/reveal')),
      verify: async () => settle(await realSource.dlsiteAction('verify')),
      disconnect: async () => settle(await realSource.dlsiteAction('disconnect')),
    },
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
export function useServiceReady(enabled: boolean) {
  return useQuery({
    enabled,
    queryKey: ['service', 'ready'],
    queryFn: ({ signal }) => realSource.ready(signal),
    staleTime: 5_000,
    gcTime: 60_000,
    retry: false,
    refetchInterval: enabled ? 15_000 : false,
  });
}

export interface Workspace {
  mode: WorkspaceMode;
  isDemo: boolean;
  /** Running on the isolated synthetic library; always labelled as such. */
  isTestLibrary: boolean;
  serviceDown: boolean;
  serviceMessage: string | null;
  retryService: () => void;
}

export function useWorkspace(): Workspace {
  const mode = useWorkspaceMode();
  const ready = useServiceReady(mode === 'real');
  const queryClient = useQueryClient();
  return {
    mode,
    isDemo: mode === 'demo',
    isTestLibrary: mode === 'real' && ready.data?.profile === 'test',
    serviceDown: mode === 'real' && (ready.isError || ready.data?.status === 'not_ready'),
    serviceMessage: ready.data?.status === 'not_ready' ? (ready.data.message ?? null) : null,
    retryService: () => {
      void ready.refetch();
      void queryClient.invalidateQueries({ queryKey: realRoot });
    },
  };
}

/** Empty in real mode: demo tasks may still be finishing but never show there. */
export function useDemoTasks(): readonly DemoTask[] {
  const mode = useWorkspaceMode();
  const tasks = useSyncExternalStore(demoTasks.subscribe, demoTasks.getSnapshot);
  return mode === 'demo' ? tasks : noTasks;
}

/** Mount once: finished demo tasks refresh every cached Library/detail/Dashboard view. */
export function useDemoTaskSync() {
  const queryClient = useQueryClient();
  useEffect(
    () => onDemoTaskComplete(() => void queryClient.invalidateQueries({ queryKey: demoRoot })),
    [queryClient],
  );
}

/** Cancels the left mode's requests and drops real data from memory when leaving it. */
export function useModeCacheIsolation() {
  const queryClient = useQueryClient();
  const mode = useWorkspaceMode();
  useEffect(() => {
    const previous: WorkspaceMode = mode === 'demo' ? 'real' : 'demo';
    void queryClient.cancelQueries({ queryKey: workspaceRoot(previous) });
    if (previous === 'real') queryClient.removeQueries({ queryKey: realRoot });
  }, [mode, queryClient]);
}

export function isAccountMismatch(error: unknown): boolean {
  return error instanceof ApiError && error.code === 'account_mismatch';
}

export function isConflict(error: unknown): boolean {
  return error instanceof ApiError && error.code === 'version_conflict';
}
