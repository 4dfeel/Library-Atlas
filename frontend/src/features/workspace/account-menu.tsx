import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Clock3, LogOut, RefreshCw, Settings2 } from 'lucide-react';
import { useShell } from '@/app/shell-context';
import { AppLink } from '@/components/app-link';
import { Button } from '@/components/ui/button';
import { connectionLabels, realConnectionState } from '@/features/demo-services/labels';
import { useDlsiteConnection, type DlsiteConnection } from '@/lib/data';
import { settingsHref } from '@/lib/router';
import { formatDate } from '@/lib/utils';

function accountLabel(connection: DlsiteConnection | undefined, failed: boolean): string {
  if (failed) return '账号状态未知';
  switch (connection?.state) {
    case undefined:
      return 'DLsite';
    case 'connected':
    case 'unverified':
      return connection.accountAlias ?? 'DLsite 账号';
    case 'authenticating':
    case 'needs_verification':
      return '正在登录…';
    case 'verifying':
      return '正在确认…';
    case 'reauth_required':
      return '需要重新登录';
    default:
      return '登录 DLsite';
  }
}

/** The account at a glance, top right, in the place people look for it. */
export function AccountMenu() {
  const { connection, actions, isError } = useDlsiteConnection();
  const { notify, openSources } = useShell();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const state = connection?.state;
  const signedIn = state === 'connected' || state === 'unverified';
  const badge = realConnectionState(state ? { connection: state } : undefined);
  const verified = formatDate(connection?.lastVerifiedAt ?? null);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setOpen(false);
      buttonRef.current?.focus();
    };
    window.addEventListener('pointerdown', onPointer);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('pointerdown', onPointer);
      window.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const logOut = async () => {
    setOpen(false);
    try {
      const result = await actions.disconnect();
      if (result.state === 'not_connected') notify('已退出 DLsite 登录');
      else notify(result.message ?? '退出登录没有完成，请重试', 'error');
    } catch {
      notify('本地服务没有响应，退出登录没有完成', 'error');
    }
  };

  return (
    <div className="account-menu" ref={rootRef} data-testid="account-menu" data-state={state}>
      <button
        ref={buttonRef}
        className="account-button"
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => setOpen((value) => !value)}
      >
        <span className={`account-avatar connection-${badge}`} aria-hidden="true">
          D
          <i />
        </span>
        <span className="account-name">{accountLabel(connection, isError)}</span>
        <ChevronDown size={13} />
      </button>
      {open && (
        <div className="account-panel" data-testid="account-panel">
          <div className="account-panel-heading">
            <strong>DLsite</strong>
            <span className={`connection-badge connection-${badge}`}>
              <i />
              {isError ? '状态未知' : connectionLabels[badge]}
            </span>
          </div>
          {signedIn && connection?.accountAlias && (
            <p className="account-alias">{connection.accountAlias}</p>
          )}
          {signedIn && verified && (
            <p className="dlsite-note">
              <Clock3 size={12} />
              最近验证 {verified}
            </p>
          )}
          {connection?.message && <p className="dlsite-note">{connection.message}</p>}
          <div className="account-panel-actions">
            {signedIn ? (
              <>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setOpen(false);
                    void actions.verify().catch(() => undefined);
                  }}
                >
                  <RefreshCw size={14} />
                  重新验证
                </Button>
                <Button variant="ghost" size="sm" onClick={() => void logOut()}>
                  <LogOut size={14} />
                  退出登录
                </Button>
              </>
            ) : (
              <Button
                size="sm"
                onClick={() => {
                  setOpen(false);
                  openSources();
                }}
              >
                {state === 'not_connected' || state === 'reauth_required'
                  ? '登录 DLsite'
                  : '查看状态'}
              </Button>
            )}
            <AppLink
              to={settingsHref}
              className="button button-ghost button-sm"
              onNavigate={() => setOpen(false)}
            >
              <Settings2 size={14} />
              设置
            </AppLink>
          </div>
        </div>
      )}
    </div>
  );
}
