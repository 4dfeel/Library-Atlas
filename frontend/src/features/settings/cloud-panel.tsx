import { useState, type FormEvent } from 'react';
import { CircleAlert, CircleCheck, Cloud, LoaderCircle, Unplug } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useCloudStatus } from '@/lib/data';

/**
 * Connecting the user's own Google Drive. Sign-in happens in their browser, on Google's page, and
 * Atlas never sees the password. The client ID comes from a project they own.
 */
export function CloudPanel() {
  const { status, actions, error } = useCloudStatus();
  const [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');
  if (!status) return <p className="settings-note">正在读取…</p>;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void actions
      .connect(clientId.trim() ? { clientId: clientId.trim(), clientSecret } : null)
      .then(() => setClientSecret(''));
  };

  return (
    <div className="cloud-panel" data-testid="cloud-panel">
      <p className="settings-note">
        把已设置存档位置的游戏存档备份到你自己的 Google
        Drive，换电脑时可以恢复。只上传存档，不上传游戏本体。这是 Atlas 的云存档，不是 DLsite
        官方功能。
      </p>
      {status.connected ? (
        <>
          <p className="dlsite-note" role="status" data-testid="cloud-connected">
            <CircleCheck size={14} />
            已连接：{status.accountName} · 这台电脑显示为 {status.deviceName}
          </p>
          <label className="scan-deep">
            <input
              type="checkbox"
              data-testid="cloud-auto-check"
              checked={status.autoCheck}
              onChange={(event) => void actions.options(event.target.checked, status.autoBackup)}
            />
            启动游戏前先检查云端。有更新或冲突时会先问你，不会自动覆盖本机存档。
          </label>
          <label className="scan-deep">
            <input
              type="checkbox"
              data-testid="cloud-auto-backup"
              checked={status.autoBackup}
              onChange={(event) => void actions.options(status.autoCheck, event.target.checked)}
            />
            从 Atlas
            启动的游戏关闭后自动备份。通过启动器再打开游戏的作品无法判断何时结束，仍需手动备份。
          </label>
          <div className="dlsite-actions">
            <Button
              variant="ghost"
              size="sm"
              data-testid="cloud-disconnect"
              onClick={() => void actions.disconnect()}
            >
              <Unplug size={14} />
              断开这台电脑
            </Button>
            <span className="settings-note">云端的备份和本机存档都会保留。</span>
          </div>
        </>
      ) : (
        <form className="cloud-form" onSubmit={submit}>
          <details open={!status.configured}>
            <summary>第一次使用：创建你自己的 Google 客户端</summary>
            <ol className="cloud-steps">
              <li>打开 console.cloud.google.com，新建一个项目。</li>
              <li>在“API 和服务 → 库”里启用 Google Drive API。</li>
              <li>
                配置 OAuth 同意屏幕，把你自己的 Google
                账号加为测试用户。项目停留在“测试”状态时，授权 7
                天就会过期，要重新连接；不想反复连接可以点“发布应用”。
              </li>
              <li>
                “凭据 → 创建凭据 → OAuth 客户端 ID”，应用类型选“桌面应用”，把得到的客户端 ID
                填到下面。
              </li>
            </ol>
            <p className="settings-note">
              权限只有 drive.file：Atlas
              只能看到自己创建的文件，看不到你网盘里的其他内容。两台电脑要用同一个客户端 ID。
            </p>
          </details>
          <Input
            aria-label="客户端 ID"
            placeholder={status.configured ? '客户端 ID（已保存，不改可留空）' : '客户端 ID'}
            spellCheck={false}
            autoComplete="off"
            value={clientId}
            onChange={(event) => setClientId(event.target.value)}
          />
          <Input
            aria-label="客户端密钥"
            type="password"
            placeholder="客户端密钥（如果 Google 给了就填，存在 Windows 凭据管理器）"
            autoComplete="off"
            value={clientSecret}
            onChange={(event) => setClientSecret(event.target.value)}
          />
          <div className="dlsite-actions">
            <Button
              size="sm"
              type="submit"
              data-testid="cloud-connect"
              disabled={status.connecting || (!status.configured && !clientId.trim())}
            >
              {status.connecting ? (
                <LoaderCircle size={14} className="spin" />
              ) : (
                <Cloud size={14} />
              )}
              连接 Google Drive
            </Button>
          </div>
          {status.connecting && (
            <p className="dlsite-note" role="status" data-testid="cloud-connecting">
              请在打开的浏览器页面里完成授权，5 分钟内有效。
            </p>
          )}
        </form>
      )}
      {(error ?? status.problem) && (
        <p className="dlsite-message" role="alert" data-testid="cloud-problem">
          <CircleAlert size={14} />
          {error ?? status.problem}
        </p>
      )}
    </div>
  );
}
