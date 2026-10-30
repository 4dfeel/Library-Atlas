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
  WorkKind,
} from './types';
export {
  getDemoEditCount,
  useGameDetail,
  useLibrary,
  useResetDemoEdits,
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
