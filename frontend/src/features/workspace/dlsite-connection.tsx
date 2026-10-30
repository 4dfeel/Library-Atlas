import { useState, type FormEvent } from 'react';
import {
  CircleAlert,
  Clock3,
  ExternalLink,
  LoaderCircle,
  LogOut,
  RefreshCw,
  Trash2,
  X,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { isAccountMismatch, useDlsiteConnection, type DlsiteConnection } from '@/lib/data';
import { formatDate } from '@/lib/utils';

function LoginForm({
  connection,
  actions,
}: {
  connection: DlsiteConnection;
  actions: ReturnType<typeof useDlsiteConnection>['actions'];
}) {
  // The password lives only in this component and only until the service accepts it.
  const [loginId, setLoginId] = useState('');
  const [password, setPassword] = useState('');
  const [switching, setSwitching] = useState(false);
  const [remember, setRemember] = useState(false);
  const [typing, setTyping] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!loginId.trim() || !password || sending) return;
    setSending(true);
    setError(null);
    try {
      await actions.login(loginId, password, switching, remember);
      setPassword('');
      setSwitching(false);
    } catch (failure) {
      if (isAccountMismatch(failure)) setSwitching(true);
      else {
        setPassword('');
        setError(failure instanceof Error ? failure.message : '登录没有开始，请重试。');
      }
    } finally {
      setSending(false);
    }
  };

  const run = async (action: () => Promise<unknown>) => {
    setError(null);
    try {
      await action();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '操作没有完成，请重试。');
    }
  };

  if (connection.rememberedAccount && !typing)
    return (
      <div className="dlsite-login" data-testid="dlsite-saved-login">
        {connection.message && (
          <p className="dlsite-message" role="alert">
            <CircleAlert size={14} />
            {connection.message}
          </p>
        )}
        {error && (
          <p className="dlsite-message" role="alert">
            <CircleAlert size={14} />
            {error}
          </p>
        )}
        <p className="dlsite-saved-account">{connection.rememberedAccount}</p>
        <p className="dlsite-note">账号和密码已保存在 Windows 凭据管理器，点一下就能登录。</p>
        <div className="dlsite-actions">
          <Button size="sm" onClick={() => void run(actions.loginWithSaved)}>
            登录
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setTyping(true)}>
            使用其他账号
          </Button>
          <Button variant="ghost" size="sm" onClick={() => void run(actions.forgetSaved)}>
            <Trash2 size={14} />
            忘记保存的密码
          </Button>
        </div>
      </div>
    );

  return (
    <form className="dlsite-login" onSubmit={(event) => void submit(event)} autoComplete="off">
      {connection.message && (
        <p className="dlsite-message" role="alert">
          <CircleAlert size={14} />
          {connection.message}
        </p>
      )}
      {error && (
        <p className="dlsite-message" role="alert">
          <CircleAlert size={14} />
          {error}
        </p>
      )}
      {switching && (
        <p className="dlsite-message" role="alert" data-testid="account-mismatch">
          <CircleAlert size={14} />
          这个账号和之前连接的不是同一个。再次点击登录即确认切换，已有的作品不会被删除。
        </p>
      )}
      <label>
        <span>DLsite 账号</span>
        <Input
          value={loginId}
          onChange={(event) => setLoginId(event.target.value)}
          autoComplete="off"
          spellCheck={false}
          maxLength={256}
          required
        />
      </label>
      <label>
        <span>密码</span>
        <Input
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="new-password"
          maxLength={256}
          required
        />
      </label>
      <label className="dlsite-remember">
        <input
          type="checkbox"
          checked={remember}
          onChange={(event) => setRemember(event.target.checked)}
        />
        <span>记住账号和密码</span>
      </label>
      <p className="dlsite-note">
        {remember
          ? '登录成功后保存在 Windows 凭据管理器，下次点一下就能登录。可以随时忘记。'
          : '账号和密码只用于这次登录，Atlas 不会保存密码。'}
      </p>
      <div className="dlsite-actions">
        <Button type="submit" size="sm" disabled={sending || !loginId.trim() || !password}>
          {sending && <LoaderCircle size={14} className="spin" />}
          {switching ? '确认切换并登录' : '登录'}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={sending}
          onClick={() => void actions.loginWithWindow().catch(() => undefined)}
        >
          <ExternalLink size={14} />
          改用网页登录
        </Button>
      </div>
    </form>
  );
}

/** Everything about the real DLsite connection. The session itself never reaches the page. */
export function DlsiteConnectionPanel() {
  const { connection, actions, isError } = useDlsiteConnection();
  if (isError)
    return (
      <p className="dlsite-message" role="alert">
        <CircleAlert size={14} />
        本地服务没有响应，暂时无法读取连接状态。
      </p>
    );
  if (!connection) return null;
  const verified = formatDate(connection.lastVerifiedAt ?? null);
  switch (connection.state) {
    case 'authenticating':
    case 'verifying':
      return (
        <div className="dlsite-progress" role="status" data-testid="dlsite-progress">
          <LoaderCircle size={15} className="spin" />
          <span>{connection.state === 'verifying' ? '正在确认登录状态…' : '正在登录 DLsite…'}</span>
          {connection.state === 'authenticating' && (
            <Button variant="ghost" size="sm" onClick={() => void actions.cancel()}>
              <X size={14} />
              取消
            </Button>
          )}
        </div>
      );
    case 'needs_verification':
      return (
        <div className="dlsite-verify" role="status" data-testid="dlsite-verification">
          <p>
            DLsite
            要求一次额外验证，这一步只能由你本人完成。请在弹出的窗口里完成，完成后会自动回到这里。
          </p>
          <div className="dlsite-actions">
            <Button variant="secondary" size="sm" onClick={() => void actions.reveal()}>
              回到验证窗口
            </Button>
            <Button variant="ghost" size="sm" onClick={() => void actions.cancel()}>
              <X size={14} />
              取消
            </Button>
          </div>
        </div>
      );
    case 'connected':
    case 'unverified':
      return (
        <div className="dlsite-connected" data-testid="dlsite-connected">
          {connection.message && (
            <p className="dlsite-message" role="status">
              <CircleAlert size={14} />
              {connection.message}
            </p>
          )}
          <p className="dlsite-note">
            {verified && (
              <>
                <Clock3 size={12} />
                最近验证 {verified} ·{' '}
              </>
            )}
            作品同步将在后续版本开放。
          </p>
          <div className="dlsite-actions">
            <Button variant="secondary" size="sm" onClick={() => void actions.verify()}>
              <RefreshCw size={14} />
              重新验证
            </Button>
            <Button variant="ghost" size="sm" onClick={() => void actions.disconnect()}>
              <LogOut size={14} />
              退出登录
            </Button>
          </div>
          <p className="dlsite-note">退出登录只清除 Atlas 保存的登录，作品和备注不受影响。</p>
        </div>
      );
    case 'disconnect_failed':
      return (
        <div className="dlsite-connected">
          <p className="dlsite-message" role="alert">
            <CircleAlert size={14} />
            {connection.message ?? '已停用这个登录，但清理没有完成。'}
          </p>
          <Button variant="secondary" size="sm" onClick={() => void actions.disconnect()}>
            重试退出登录
          </Button>
        </div>
      );
    default:
      return <LoginForm connection={connection} actions={actions} />;
  }
}
