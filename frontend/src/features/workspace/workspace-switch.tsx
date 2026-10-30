import { Check, Database, FlaskConical } from 'lucide-react';
import { demoAvailable, setWorkspaceMode, useWorkspaceMode, type WorkspaceMode } from '@/lib/data';
import { matchRoute, navigate } from '@/lib/router';

const options: { mode: WorkspaceMode; icon: typeof Database; title: string; note: string }[] = [
  {
    mode: 'real',
    icon: Database,
    title: '我的资料库',
    note: '保存在本机的真实资料。需要本地服务运行。',
  },
  {
    mode: 'demo',
    icon: FlaskConical,
    title: '演示空间',
    note: '独立的合成作品，只存在于这个浏览器。',
  },
];

/** The two libraries never share data; switching only changes which one is showing. */
export function WorkspaceSwitch() {
  const mode = useWorkspaceMode();
  const choose = (next: WorkspaceMode) => {
    if (next === mode) return;
    setWorkspaceMode(next);
    // A work belongs to one library, and URL state describes the library being left.
    const route = matchRoute(window.location.pathname);
    navigate(route.name === 'game' ? '/library' : window.location.pathname, { replace: true });
  };
  if (!demoAvailable) return null;
  return (
    <div className="workspace-switch" role="group" aria-label="选择资料空间">
      {options.map(({ mode: value, icon: Icon, title, note }) => (
        <button
          key={value}
          data-mode={value}
          className={mode === value ? 'selected' : ''}
          aria-pressed={mode === value}
          onClick={() => choose(value)}
        >
          <Icon size={18} />
          <span>
            {title}
            <small>{note}</small>
          </span>
          {mode === value && <Check size={16} />}
        </button>
      ))}
    </div>
  );
}
