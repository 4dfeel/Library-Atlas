import * as TooltipPrimitive from '@radix-ui/react-tooltip';
import { AnimatePresence, MotionConfig, motion, useReducedMotion } from 'motion/react';
import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import {
  Check,
  ChevronRight,
  CircleAlert,
  CircleHelp,
  Download,
  FolderHeart,
  Gamepad2,
  Home,
  Layers3,
  LibraryBig,
  LockKeyhole,
  Menu,
  RotateCcw,
  ChartColumn,
  Settings2,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Tooltip } from '@/components/ui/tooltip';
import {
  getDemoEditCount,
  isActiveTask,
  useDemoTasks,
  useDownloads,
  useExtractions,
  useDemoTaskSync,
  useModeCacheIsolation,
  useResetDemoEdits,
  useWorkspace,
  type DemoSize,
} from '@/lib/data';
import { AppLink } from '@/components/app-link';
import {
  dashboardHref,
  downloadsHref,
  libraryHref,
  matchRoute,
  navigate,
  settingsHref,
  useLocationKey,
} from '@/lib/router';
import { DashboardPage } from '@/features/dashboard/dashboard-page';
import { SourcesDialog } from '@/features/demo-services/sources-dialog';
import { MiniPlayer } from '@/features/audio/audio-panel';
import { ActivityPage } from '@/features/activity/activity-page';
import { CollectionsPage } from '@/features/collections/collections-page';
import { DownloadBar, DownloadsPage } from '@/features/downloads/downloads-page';
import { TasksDialog } from '@/features/demo-services/tasks-dialog';
import { AccountMenu } from '@/features/workspace/account-menu';
import { WorkspaceSwitch } from '@/features/workspace/workspace-switch';
import { SettingsPage } from '@/features/settings/settings-page';
import { RouteBoundary } from './route-boundary';
import { ShellContext } from './shell-context';
import { LibraryPage } from '@/features/library/library-page';
import { noteDrafts } from '@/features/game-detail/note-drafts';

// Route-level split keeps the Library bundle unchanged by the detail page.
const detailModule = () => import('@/features/game-detail/game-detail-page');
const GameDetailPage = lazy(() => detailModule().then((m) => ({ default: m.GameDetailPage })));
const GameUnavailable = lazy(() => detailModule().then((m) => ({ default: m.GameUnavailable })));

function useNarrow() {
  const [narrow, setNarrow] = useState(() => window.matchMedia('(max-width: 1280px)').matches);
  useEffect(() => {
    const query = window.matchMedia('(max-width: 1280px)');
    const update = () => setNarrow(query.matches);
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  return narrow;
}

function Brand({ collapsed }: { collapsed: boolean }) {
  return (
    <div className="brand">
      <div className="brand-mark" aria-hidden="true">
        <Layers3 size={24} strokeWidth={1.5} />
      </div>
      {!collapsed && (
        <div>
          <span>LIBRARY ATLAS</span>
          <small>你的私人作品地图</small>
        </div>
      )}
    </div>
  );
}

interface Toast {
  id: number;
  message: string;
  tone: 'success' | 'error';
}

function SoonItem({
  icon: Icon,
  label,
  title,
  collapsed,
}: {
  icon: typeof Home;
  label: string;
  title: string;
  collapsed: boolean;
}) {
  return (
    <button className="nav-item" disabled title={title} aria-label={`${label} · 稍后开放`}>
      <Icon size={19} />
      {!collapsed && (
        <>
          <span>{label}</span>
          <span className="nav-soon">稍后</span>
        </>
      )}
    </button>
  );
}

function sizeFromUrl(): DemoSize {
  return new URLSearchParams(window.location.search).get('size') === '5000' ? 5000 : 1500;
}

export function App() {
  const narrow = useNarrow();
  const [manualCollapsed, setManualCollapsed] = useState(false);
  const collapsed = narrow || manualCollapsed;
  const locationKey = useLocationKey();
  const route = matchRoute(window.location.pathname);
  const workspace = useWorkspace();
  const { mode, isDemo, isTestLibrary, serviceDown, serviceMessage, retryService } = workspace;
  const [demoSize, setSize] = useState<DemoSize>(sizeFromUrl);
  // Scale is a property of the synthetic dataset; the real library has its own size.
  const size: DemoSize = isDemo ? demoSize : 1500;
  const [aboutOpen, setAboutOpen] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [tasksOpen, setTasksOpen] = useState(false);
  const [toast, setToast] = useState<Toast | null>(null);
  const reduceMotion = useReducedMotion();
  const resetEdits = useResetDemoEdits(size);

  // Size travels in the URL; follow it when history moves between entries.
  const [sizeLocation, setSizeLocation] = useState(locationKey);
  if (sizeLocation !== locationKey) {
    setSizeLocation(locationKey);
    setSize(sizeFromUrl());
  }
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 2400);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const notify = useCallback((message: string, tone: 'success' | 'error' = 'success') => {
    setToast({ id: Date.now(), message, tone });
  }, []);
  const setDemoSize = (value: DemoSize) => {
    setSize(value);
    const url = new URL(window.location.href);
    if (value === 5000) url.searchParams.set('size', '5000');
    else url.searchParams.delete('size');
    window.history.replaceState(window.history.state, '', url);
  };
  const openAbout = useCallback(() => setAboutOpen(true), []);
  const openSources = useCallback(() => setSourcesOpen(true), []);
  // A real library has a whole page for this; the demo keeps its dialog.
  const openTasks = useCallback(() => {
    if (isDemo) setTasksOpen(true);
    else navigate(downloadsHref());
  }, [isDemo]);
  const shell = useMemo(
    () => ({ notify, openSources, openTasks }),
    [notify, openSources, openTasks],
  );
  const demoRunning = useDemoTasks().filter(isActiveTask).length;
  const realDownloads = useDownloads();
  const realExtractions = useExtractions();
  const runningTasks = isDemo
    ? demoRunning
    : realDownloads.activeCount + realExtractions.activeCount;
  useDemoTaskSync();
  useModeCacheIsolation();
  const editCount = aboutOpen ? getDemoEditCount(size) : 0;

  return (
    <MotionConfig reducedMotion="user">
      <ShellContext.Provider value={shell}>
        <TooltipPrimitive.Provider>
          <div className={`app-shell${collapsed ? ' sidebar-collapsed' : ''}`}>
            <aside className="sidebar" aria-label="主导航">
              <Brand collapsed={collapsed} />
              <div className="sidebar-nav">
                {!collapsed && <div className="nav-label">我的空间</div>}
                <AppLink
                  aria-label="首页"
                  to={dashboardHref(size)}
                  className={`nav-item${route.name === 'dashboard' ? ' active' : ''}`}
                  aria-current={route.name === 'dashboard' ? 'page' : undefined}
                >
                  <Home size={19} />
                  {!collapsed && <span>首页</span>}
                </AppLink>
                <AppLink
                  aria-label="作品库"
                  to={libraryHref(size)}
                  className={`nav-item${route.name === 'library' || route.name === 'game' ? ' active' : ''}`}
                  aria-current={route.name === 'library' ? 'page' : undefined}
                >
                  <LibraryBig size={19} />
                  {!collapsed && (
                    <>
                      <span>作品库</span>
                      <ChevronRight className="nav-chevron" size={16} />
                    </>
                  )}
                </AppLink>
                {isDemo ? (
                  <SoonItem
                    icon={FolderHeart}
                    label="收藏夹"
                    title="收藏夹将在后续阶段开放"
                    collapsed={collapsed}
                  />
                ) : (
                  <AppLink
                    aria-label="收藏夹"
                    to="/collections"
                    className={`nav-item${route.name === 'collections' ? ' active' : ''}`}
                    aria-current={route.name === 'collections' ? 'page' : undefined}
                  >
                    <FolderHeart size={19} />
                    {!collapsed && <span>收藏夹</span>}
                  </AppLink>
                )}
                {!isDemo && (
                  <AppLink
                    aria-label="游玩记录"
                    to="/activity"
                    className={`nav-item${route.name === 'activity' ? ' active' : ''}`}
                    aria-current={route.name === 'activity' ? 'page' : undefined}
                  >
                    <ChartColumn size={19} />
                    {!collapsed && <span>游玩记录</span>}
                  </AppLink>
                )}
                <SoonItem
                  icon={Gamepad2}
                  label="游玩计划"
                  title="游玩计划将在后续阶段开放"
                  collapsed={collapsed}
                />
                {!collapsed && <div className="nav-label second-label">探索与整理</div>}
                <SoonItem
                  icon={Sparkles}
                  label="发现"
                  title="个性化推荐将在后续阶段开放"
                  collapsed={collapsed}
                />
                <SoonItem
                  icon={LockKeyhole}
                  label="私人空间"
                  title="私人空间将在后续阶段开放"
                  collapsed={collapsed}
                />
              </div>
              <div className="sidebar-bottom">
                {!collapsed && (
                  <div className="local-note">
                    <ShieldCheck size={17} />
                    <span>
                      收藏属于你自己<small>本地优先，安心探索。</small>
                    </span>
                  </div>
                )}
                <AppLink
                  aria-label="设置"
                  to={settingsHref}
                  className={`nav-item${route.name === 'settings' ? ' active' : ''}`}
                  aria-current={route.name === 'settings' ? 'page' : undefined}
                >
                  <Settings2 size={19} />
                  {!collapsed && <span>设置</span>}
                </AppLink>
                <div className="sidebar-profile">
                  <span className="profile-avatar">A</span>
                  {!collapsed &&
                    (isDemo ? (
                      <span>
                        Atlas 演示空间<small>独立合成数据</small>
                      </span>
                    ) : isTestLibrary ? (
                      <span>
                        隔离测试库<small>合成样本，不是同步结果</small>
                      </span>
                    ) : (
                      <span>
                        我的资料库<small>保存在这台电脑上</small>
                      </span>
                    ))}
                  <span className="online-dot" data-offline={serviceDown} />
                </div>
              </div>
            </aside>

            <div className="workspace">
              <header className="topbar">
                <div className="topbar-left">
                  <Tooltip
                    content={
                      narrow ? '窗口较窄，侧栏已自动收起' : collapsed ? '展开侧栏' : '收起侧栏'
                    }
                  >
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={collapsed ? '展开侧栏' : '收起侧栏'}
                      disabled={narrow}
                      onClick={() => setManualCollapsed((value) => !value)}
                    >
                      <Menu size={19} />
                    </Button>
                  </Tooltip>
                  <nav className="breadcrumb" aria-label="当前位置">
                    <span className="breadcrumb-root">我的空间</span>
                    <ChevronRight size={13} />
                    {route.name === 'dashboard' ? (
                      <span aria-current="page">首页</span>
                    ) : route.name === 'library' ? (
                      <span aria-current="page">作品库</span>
                    ) : route.name === 'settings' ? (
                      <span aria-current="page">设置</span>
                    ) : route.name === 'downloads' ? (
                      <span aria-current="page">下载</span>
                    ) : (
                      <>
                        <AppLink to={libraryHref(size)} className="breadcrumb-link">
                          作品库
                        </AppLink>
                        <ChevronRight size={13} />
                        <span aria-current="page">作品详情</span>
                      </>
                    )}
                  </nav>
                </div>
                <div className="topbar-right">
                  <button
                    className="demo-indicator"
                    data-testid="workspace-indicator"
                    data-mode={
                      isDemo ? 'demo' : serviceDown ? 'offline' : isTestLibrary ? 'test' : 'real'
                    }
                    title="切换资料空间"
                    onClick={openAbout}
                  >
                    <span />
                    {isDemo
                      ? 'DEMO · 演示模式'
                      : serviceDown
                        ? '本地服务未连接'
                        : isTestLibrary
                          ? '测试库 · 合成数据'
                          : '我的资料库'}
                  </button>
                  {!isDemo && <AccountMenu />}
                  <span className="topbar-divider" />
                  <Tooltip content={isDemo ? '下载与解压任务（演示）' : '下载与解压任务'}>
                    <Button
                      size="icon"
                      variant="ghost"
                      aria-label={`下载任务${runningTasks ? `，${runningTasks} 个进行中` : ''}`}
                      className="tasks-button"
                      onClick={openTasks}
                    >
                      <Download size={18} />
                      {runningTasks > 0 && <span className="tasks-badge">{runningTasks}</span>}
                    </Button>
                  </Tooltip>
                  <Tooltip content={isDemo ? '关于本次演示' : '资料库状态'}>
                    <Button
                      size="icon"
                      variant="ghost"
                      aria-label={isDemo ? '关于演示' : '资料库状态'}
                      onClick={openAbout}
                    >
                      <CircleHelp size={18} />
                    </Button>
                  </Tooltip>
                </div>
              </header>

              <RouteBoundary key={`${mode}-${locationKey}`}>
                <Suspense fallback={<main className="detail-page" aria-busy="true" />}>
                  {route.name === 'dashboard' ? (
                    <DashboardPage key={`${mode}-dashboard-${locationKey}`} size={size} />
                  ) : route.name === 'library' ? (
                    <LibraryPage
                      key={`${mode}-library-${locationKey}`}
                      size={size}
                      onAbout={openAbout}
                      notify={notify}
                    />
                  ) : route.name === 'settings' ? (
                    <SettingsPage key={`${mode}-settings`} onDemoSettings={openAbout} />
                  ) : route.name === 'downloads' && !isDemo ? (
                    <DownloadsPage size={size} />
                  ) : route.name === 'collections' && !isDemo ? (
                    <CollectionsPage />
                  ) : route.name === 'activity' && !isDemo ? (
                    <ActivityPage />
                  ) : route.name === 'game' ? (
                    <GameDetailPage
                      key={`${mode}-${route.id}-${size}`}
                      id={route.id}
                      size={size}
                      notify={notify}
                    />
                  ) : (
                    <GameUnavailable size={size} />
                  )}
                </Suspense>
              </RouteBoundary>
              {!isDemo && <MiniPlayer />}
              {!isDemo && <DownloadBar />}
            </div>
          </div>
          <Dialog
            open={aboutOpen}
            onOpenChange={(open) => {
              setAboutOpen(open);
              if (!open) setConfirmReset(false);
            }}
            title={isDemo ? '你的演示空间' : isTestLibrary ? '隔离测试库' : '我的资料库'}
            description={
              isDemo
                ? '当前展示的作品、封面与游玩记录均为合成资料，与真实 Steam / DLsite 库存完全隔离。'
                : isTestLibrary
                  ? '这是用于验证的合成样本库，内容不是平台同步结果，也不会写入你的真实资料。'
                  : '评分、备注、状态与收藏保存在这台电脑的本地资料库中，与演示空间完全隔离。'
            }
          >
            <div className="demo-settings">
              <WorkspaceSwitch />
              {!isDemo && (
                <div className="demo-explanation" data-testid="service-status">
                  <ShieldCheck size={18} />
                  <p>
                    {serviceDown
                      ? (serviceMessage ??
                        '本地服务没有响应。你的资料没有受到影响；请确认服务已启动。')
                      : '本地服务已连接。下载和解压将在后续版本开放。'}
                  </p>
                  {serviceDown && (
                    <Button variant="ghost" size="sm" onClick={retryService}>
                      <RotateCcw size={14} />
                      重试
                    </Button>
                  )}
                </div>
              )}
              {isDemo && (
                <>
                  <div>
                    <span className="eyebrow">DATA SCENARIO</span>
                    <h3>选择收藏规模</h3>
                    <p>固定种子生成；两种规模共用前 1500 条记录及其演示修改。</p>
                  </div>
                  <div className="scenario-buttons">
                    {([1500, 5000] as const).map((value) => (
                      <button
                        key={value}
                        className={size === value ? 'selected' : ''}
                        aria-pressed={size === value}
                        onClick={() => setDemoSize(value)}
                      >
                        <span>
                          {value.toLocaleString('zh-CN')}
                          <small>部作品</small>
                        </span>
                        {size === value && <Check size={18} />}
                      </button>
                    ))}
                  </div>
                  <div className="demo-explanation">
                    <ShieldCheck size={18} />
                    <p>
                      私人、隐藏与待确认条目已在数据选择层排除，按 ID
                      读取和修改同样受限。评分、备注、状态与收藏只保存在本浏览器的演示存储中，不会写入真实资料。
                    </p>
                  </div>
                  <div className="demo-reset">
                    {confirmReset ? (
                      <>
                        <p role="alert">
                          将清除本浏览器中 {editCount.toLocaleString('zh-CN')}{' '}
                          部作品的演示修改（评分、备注、状态、收藏），恢复为初始合成资料。未保存的备注草稿也会丢弃。此操作无法撤销。
                        </p>
                        <div>
                          <Button
                            variant="secondary"
                            size="sm"
                            disabled={resetEdits.isPending}
                            onClick={() =>
                              resetEdits.mutate(undefined, {
                                onSuccess: () => {
                                  noteDrafts.clear();
                                  setConfirmReset(false);
                                  notify('演示修改已重置');
                                },
                                onError: (error) => notify(error.message, 'error'),
                              })
                            }
                          >
                            <RotateCcw size={14} />
                            确认重置
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => setConfirmReset(false)}>
                            取消
                          </Button>
                        </div>
                      </>
                    ) : (
                      <>
                        <p>
                          已修改 {editCount.toLocaleString('zh-CN')}{' '}
                          部作品。重置只影响本浏览器的演示存储。
                        </p>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={editCount === 0}
                          onClick={() => setConfirmReset(true)}
                        >
                          <RotateCcw size={14} />
                          重置演示修改…
                        </Button>
                      </>
                    )}
                  </div>
                </>
              )}
              <Button variant="secondary" onClick={() => setAboutOpen(false)}>
                继续浏览
                <ChevronRight size={15} />
              </Button>
            </div>
          </Dialog>
          <AnimatePresence>
            {toast && (
              <motion.div
                key={toast.id}
                className={`toast toast-${toast.tone}`}
                role={toast.tone === 'error' ? 'alert' : 'status'}
                initial={{ opacity: 0, y: reduceMotion ? 0 : 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
              >
                {toast.tone === 'error' ? <CircleAlert size={16} /> : <Check size={16} />}
                {toast.message}
              </motion.div>
            )}
          </AnimatePresence>
          <SourcesDialog
            open={sourcesOpen}
            onOpenChange={setSourcesOpen}
            size={size}
            demoEnabled={isDemo}
          />
          <TasksDialog
            open={tasksOpen}
            onOpenChange={setTasksOpen}
            size={size}
            demoEnabled={isDemo}
          />
        </TooltipPrimitive.Provider>
      </ShellContext.Provider>
    </MotionConfig>
  );
}
