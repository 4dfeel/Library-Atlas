export {
  defaultLibraryFilters,
  GameUnavailableError,
  GameUpdateError,
  noteMaxLength,
  ratingScale,
  workKinds,
} from './types';
export type {
  DemoSize,
  DemoScenario,
  Game,
  GameAchievements,
  GameDetail,
  GameStatus,
  GameUpdate,
  LibraryFilters,
  LibraryResult,
  LibrarySort,
  LibrarySource,
  Platform,
  Visibility,
  WorkFileInfo,
  WorkKind,
} from './types';
export { ApiError, ServiceUnavailableError } from './api-client';
export type { ConnectionStatus, LibrarySummary, SourceStatus } from './real-source';
export { demoAvailable, setWorkspaceMode, useWorkspaceMode, type WorkspaceMode } from './workspace';
export {
  getDemoEditCount,
  isConflict,
  useGameDetail,
  useLibraryCollection,
  useModeCacheIsolation,
  useRealSources,
  useResetDemoEdits,
  useServiceReady,
  useWorkspace,
  useConnections,
  useDashboard,
  useDemoTasks,
  useDemoTaskSync,
  useToggleFavorite,
  useUpdateGame,
} from './hooks';
export { getBackdropSource, getCoverSource } from './covers';
export {
  dashboardScopes,
  scopeLibraryFilters,
  type DashboardResult,
  type DashboardScope,
  type Recommendation,
} from './dashboard';
export type { ConnectionState, SourceConnection } from './demo-connections';
export { isActiveTask, type DemoTask, type TaskPhase } from './demo-tasks';
export { demoConnections, demoTasks, startDemoDownload } from './demo-runtime';
