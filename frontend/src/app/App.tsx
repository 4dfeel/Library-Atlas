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
import { useDownloads, useExtractions, useWorkspace } from '@/lib/data';
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
import { MiniPlayer } from '@/features/audio/audio-panel';
import { ActivityPage } from '@/features/activity/activity-page';
import { CollectionsPage } from '@/features/collections/collections-page';
import { DownloadBar, DownloadsPage } from '@/features/downloads/downloads-page';
import { AccountMenu } from '@/features/workspace/account-menu';
import { SourcesDialog } from '@/features/workspace/sources-dialog';
import { SettingsPage } from '@/features/settings/settings-page';
import { RouteBoundary } from './route-boundary';
import { ShellContext } from './shell-context';
import { LibraryPage } from '@/features/library/library-page';

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

export function App() {
  const narrow = useNarrow();
  const [manualCollapsed, setManualCollapsed] = useState(false);
  const collapsed = narrow || manualCollapsed;
  const locationKey = useLocationKey();
  const route = matchRoute(window.location.pathname);
  const { isTestLibrary, serviceDown, serviceMessage, retryService } = useWorkspace();
  const [aboutOpen, setAboutOpen] = useState(false);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [toast, setToast] = useState<Toast | null>(null);
  const reduceMotion = useReducedMotion();
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 2400);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const notify = useCallback((message: string, tone: 'success' | 'error' = 'success') => {
    setToast({ id: Date.now(), message, tone });
  }, []);
  const openAbout = useCallback(() => setAboutOpen(true), []);
  const openSources = useCallback(() => setSourcesOpen(true), []);
  const openTasks = useCallback(() => navigate(downloadsHref()), []);
  const shell = useMemo(
    () => ({ notify, openSources, openTasks }),
    [notify, openSources, openTasks],
  );
  const runningTasks = useDownloads().activeCount + useExtractions().activeCount;

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
                  to={dashboardHref()}
                  className={`nav-item${route.name === 'dashboard' ? ' active' : ''}`}
                  aria-current={route.name === 'dashboard' ? 'page' : undefined}
                >
                  <Home size={19} />
                  {!collapsed && <span>首页</span>}
                </AppLink>
                <AppLink
                  aria-label="作品库"
                  to={libraryHref()}
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
                <AppLink
                  aria-label="收藏夹"
                  to="/collections"
                  className={`nav-item${route.name === 'collections' ? ' active' : ''}`}
                  aria-current={route.name === 'collections' ? 'page' : undefined}
                >
                  <FolderHeart size={19} />
                  {!collapsed && <span>收藏夹</span>}
                </AppLink>
                <AppLink
                  aria-label="游玩记录"
                  to="/activity"
                  className={`nav-item${route.name === 'activity' ? ' active' : ''}`}
                  aria-current={route.name === 'activity' ? 'page' : undefined}
                >
                  <ChartColumn size={19} />
                  {!collapsed && <span>游玩记录</span>}
                </AppLink>
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
                    (isTestLibrary ? (
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
                        <AppLink to={libraryHref()} className="breadcrumb-link">
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
                    className="library-indicator"
                    data-testid="workspace-indicator"
                    data-mode={serviceDown ? 'offline' : isTestLibrary ? 'test' : 'real'}
                    title="资料库状态"
                    onClick={openAbout}
                  >
                    <span />
                    {serviceDown
                      ? '本地服务未连接'
                      : isTestLibrary
                        ? '测试库 · 合成数据'
                        : '我的资料库'}
                  </button>
                  <AccountMenu />
                  <span className="topbar-divider" />
                  <Tooltip content="下载与解压任务">
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
                  <Tooltip content="资料库状态">
                    <Button size="icon" variant="ghost" aria-label="资料库状态" onClick={openAbout}>
                      <CircleHelp size={18} />
                    </Button>
                  </Tooltip>
                </div>
              </header>

              <RouteBoundary key={locationKey}>
                <Suspense fallback={<main className="detail-page" aria-busy="true" />}>
                  {route.name === 'dashboard' ? (
                    <DashboardPage key={`dashboard-${locationKey}`} />
                  ) : route.name === 'library' ? (
                    <LibraryPage
                      key={`library-${locationKey}`}
                      onAbout={openAbout}
                      notify={notify}
                    />
                  ) : route.name === 'settings' ? (
                    <SettingsPage />
                  ) : route.name === 'downloads' ? (
                    <DownloadsPage />
                  ) : route.name === 'collections' ? (
                    <CollectionsPage />
                  ) : route.name === 'activity' ? (
                    <ActivityPage />
                  ) : route.name === 'game' ? (
                    <GameDetailPage key={route.id} id={route.id} notify={notify} />
                  ) : (
                    <GameUnavailable />
                  )}
                </Suspense>
              </RouteBoundary>
              <MiniPlayer />
              <DownloadBar />
            </div>
          </div>
          <Dialog
            open={aboutOpen}
            onOpenChange={setAboutOpen}
            title={isTestLibrary ? '隔离测试库' : '我的资料库'}
            description={
              isTestLibrary
                ? '这是用于验证的合成样本库，内容不是平台同步结果，也不会写入你的真实资料。'
                : '评分、备注、状态与收藏保存在这台电脑的本地资料库中。'
            }
          >
            <div className="about-panel">
              <div className="about-note" data-testid="service-status">
                <ShieldCheck size={18} />
                <p>
                  {serviceDown
                    ? (serviceMessage ??
                      '本地服务没有响应。你的资料没有受到影响；请确认服务已启动。')
                    : '本地服务已连接。'}
                </p>
                {serviceDown && (
                  <Button variant="ghost" size="sm" onClick={retryService}>
                    <RotateCcw size={14} />
                    重试
                  </Button>
                )}
              </div>
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
          <SourcesDialog open={sourcesOpen} onOpenChange={setSourcesOpen} />
        </TooltipPrimitive.Provider>
      </ShellContext.Provider>
    </MotionConfig>
  );
}
