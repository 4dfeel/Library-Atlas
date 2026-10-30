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
  useDemoTaskSync,
  useResetDemoEdits,
  type DemoSize,
} from '@/lib/data';
import { AppLink } from '@/components/app-link';
import { dashboardHref, libraryHref, matchRoute, useLocationKey } from '@/lib/router';
import { DashboardPage } from '@/features/dashboard/dashboard-page';
import { SourcesDialog } from '@/features/demo-services/sources-dialog';
import { TasksDialog } from '@/features/demo-services/tasks-dialog';
import { ShellContext } from './shell-context';
import { LibraryPage } from '@/features/library/library-page';
import { noteDrafts } from '@/features/game-detail/note-drafts';

const demoEnabled = import.meta.env.VITE_DEMO_MODE !== 'false';
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
  const [size, setSize] = useState<DemoSize>(sizeFromUrl);
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
  const openTasks = useCallback(() => setTasksOpen(true), []);
  const shell = useMemo(
    () => ({ notify, openSources, openTasks }),
    [notify, openSources, openTasks],
  );
  const runningTasks = useDemoTasks().filter(isActiveTask).length;
  useDemoTaskSync();
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
                <SoonItem
                  icon={FolderHeart}
                  label="收藏夹"
                  title="收藏夹将在后续阶段开放"
                  collapsed={collapsed}
                />
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
                <button className="nav-item" onClick={openAbout} title="演示设置">
                  <Settings2 size={19} />
                  {!collapsed && <span>演示设置</span>}
                </button>
                <div className="sidebar-profile">
                  <span className="profile-avatar">A</span>
                  {!collapsed && (
                    <span>
                      Atlas 演示空间<small>独立合成数据</small>
                    </span>
                  )}
                  <span className="online-dot" />
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
                  <span className="demo-indicator">
                    <span />
                    {demoEnabled ? 'DEMO · 演示模式' : '真实数据尚未接入'}
                  </span>
                  <span className="topbar-divider" />
                  <Tooltip
                    content={demoEnabled ? '下载与解压任务（演示）' : '下载与解压（尚未接入）'}
                  >
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
                  <Tooltip content="关于本次演示">
                    <Button size="icon" variant="ghost" aria-label="关于演示" onClick={openAbout}>
                      <CircleHelp size={18} />
                    </Button>
                  </Tooltip>
                </div>
              </header>

              <Suspense fallback={<main className="detail-page" aria-busy="true" />}>
                {route.name === 'dashboard' ? (
                  <DashboardPage
                    key={`dashboard-${locationKey}`}
                    size={size}
                    demoEnabled={demoEnabled}
                  />
                ) : route.name === 'library' ? (
                  <LibraryPage
                    key={`library-${locationKey}`}
                    size={size}
                    demoEnabled={demoEnabled}
                    onAbout={openAbout}
                    notify={notify}
                  />
                ) : route.name === 'game' ? (
                  <GameDetailPage
                    key={`${route.id}-${size}`}
                    id={route.id}
                    size={size}
                    demoEnabled={demoEnabled}
                    notify={notify}
                  />
                ) : (
                  <GameUnavailable size={size} />
                )}
              </Suspense>
            </div>
          </div>
          <Dialog
            open={aboutOpen}
            onOpenChange={(open) => {
              setAboutOpen(open);
              if (!open) setConfirmReset(false);
            }}
            title="你的演示空间"
            description="当前展示的作品、封面与游玩记录均为合成资料，与真实 Steam / DLsite 库存完全隔离。"
          >
            <div className="demo-settings">
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
            demoEnabled={demoEnabled}
          />
          <TasksDialog
            open={tasksOpen}
            onOpenChange={setTasksOpen}
            size={size}
            demoEnabled={demoEnabled}
          />
        </TooltipPrimitive.Provider>
      </ShellContext.Provider>
    </MotionConfig>
  );
}
