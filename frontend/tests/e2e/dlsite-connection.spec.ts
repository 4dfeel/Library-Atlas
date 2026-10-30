import { expect, test, type Page } from '@playwright/test';
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { noHorizontalScroll, viewportTag } from './evidence';
import { RealService, enterRealMode } from './real-service';

/**
 * The real service and database, with the platform replaced by the test profile's stand-ins.
 * Proves state handling and secret handling, never that a real DLsite login works.
 */
const evidenceDir = resolve('../artifacts/phase-2-checkpoint-2');
const coreProjects = ['1080p', 'narrow', '4k-200'];
const password = 'SENTINEL-PASSWORD-不应出现-e2e';

async function shot(page: Page, name: string) {
  const info = test.info();
  const dir = resolve(evidenceDir, 'screenshots', info.project.name);
  await mkdir(dir, { recursive: true });
  await page.screenshot({
    path: resolve(dir, `${name}__${viewportTag(page, info)}.png`),
    animations: 'disabled',
  });
}

let service: RealService;

async function control(values: Record<string, string>) {
  await writeFile(join(service.dataDir, 'fake-platform.json'), JSON.stringify(values));
}

async function openPanel(page: Page) {
  await enterRealMode(page);
  await page.goto(`${service.origin}/library`);
  await expect(page.getByTestId('workspace-indicator')).toHaveText('测试库 · 合成数据');
  await page.getByRole('link', { name: '首页', exact: true }).click();
  await page.getByRole('button', { name: '管理来源连接' }).click();
  await expect(page.getByTestId('real-sources')).toBeVisible();
}

async function submitLogin(page: Page, account: string) {
  await page.getByLabel('DLsite 账号').fill(account);
  await page.getByLabel('密码', { exact: true }).fill(password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
}

/** The fake platform picks its behavior by account name, so tests use several accounts. */
async function signIn(page: Page, account: string) {
  await submitLogin(page, account);
  const confirm = page.getByRole('button', { name: '确认切换并登录' });
  // Wait for the service's answer itself, whichever it is, rather than for a fixed time.
  await confirm
    .or(page.getByTestId('dlsite-progress'))
    .or(page.getByTestId('dlsite-verification'))
    .or(page.getByTestId('dlsite-connected'))
    .or(page.locator('.dlsite-message'))
    .first()
    .waitFor();
  if (await confirm.isVisible()) await confirm.click();
}

const row = (page: Page) => page.locator('[data-source="dlsite"]').last();

test.beforeAll(async () => {
  test.skip(!coreProjects.includes(test.info().project.name), 'core tiers only');
  test.setTimeout(120_000);
  service = await RealService.create(12, 8795);
  await service.start();
});
test.afterAll(async () => service?.dispose());

test.beforeEach(async () => {
  await control({});
  // Every test starts disconnected, from the same account.
  const session = await (await fetch(`${service.origin}/api/v1/session`)).json();
  await fetch(`${service.origin}/api/v1/sources/dlsite/login/cancel`, {
    method: 'POST',
    headers: { Origin: service.origin, 'X-Atlas-CSRF': session.csrfToken },
  });
  await fetch(`${service.origin}/api/v1/sources/dlsite/disconnect`, {
    method: 'POST',
    headers: { Origin: service.origin, 'X-Atlas-CSRF': session.csrfToken },
  });
  await fetch(`${service.origin}/api/v1/sources/dlsite/saved-login/forget`, {
    method: 'POST',
    headers: { Origin: service.origin, 'X-Atlas-CSRF': session.csrfToken },
  });
});

test('login happens inside Atlas and survives a real restart', async ({ page }) => {
  await openPanel(page);
  await expect(row(page)).toContainText('未连接');
  await expect(row(page)).toContainText('不会保存密码');
  await noHorizontalScroll(page);
  await shot(page, 'dlsite-login-form');

  const sent: string[] = [];
  page.on('request', (request) => sent.push(request.url()));
  await signIn(page, 'ok@example.test');
  await expect(row(page).getByTestId('dlsite-connected')).toBeVisible();
  await expect(row(page)).toContainText('已连接');
  await expect(row(page).getByTestId('dlsite-sync')).toBeVisible();
  await shot(page, 'dlsite-connected');
  expect(sent.join('\n')).not.toContain(password);
  // The form is gone and the password is nowhere in the page or its storage.
  expect(await page.content()).not.toContain(password);
  const stored = await page.evaluate(() => JSON.stringify({ ...window.localStorage }));
  expect(stored).not.toContain(password);
  expect(stored).not.toContain('ok@example.test');

  // Signing in adds no works and shows nothing as synced.
  const works = await (await fetch(`${service.origin}/api/v1/works`)).json();
  expect(works.totalVisible).toBe(12);
  await expect(row(page)).toContainText('暂无记录');

  await service.restart();
  await openPanel(page);
  await expect(row(page).getByTestId('dlsite-connected')).toBeVisible();
  await expect(row(page)).toContainText('已连接');
  await expect(page.getByLabel('密码', { exact: true })).toHaveCount(0);

  await row(page).getByRole('button', { name: '退出登录' }).click();
  await expect(row(page)).toContainText('未连接');
  await expect(page.getByLabel('密码', { exact: true })).toBeVisible();
  const works2 = await (await fetch(`${service.origin}/api/v1/works`)).json();
  expect(works2.totalVisible).toBe(12);

  await service.restart();
  await openPanel(page);
  await expect(row(page)).toContainText('未连接');

  for (const name of await readdir(service.dataDir, { recursive: true })) {
    const path = join(service.dataDir, String(name));
    const content = await readFile(path).catch(() => null);
    if (content) expect(content.includes(password), String(name)).toBe(false);
  }
});

test('wrong password says so, keeps the account and asks for the password again', async ({
  page,
}) => {
  await openPanel(page);
  await signIn(page, 'bad@example.test');
  await expect(row(page)).toContainText('账号或密码不正确');
  await expect(page.getByLabel('DLsite 账号')).toHaveValue('bad@example.test');
  await expect(page.getByLabel('密码', { exact: true })).toHaveValue('');
  await expect(row(page)).toContainText('未连接');
  await shot(page, 'dlsite-bad-credentials');
});

test('a login can be cancelled and leaves nothing connected', async ({ page }) => {
  await openPanel(page);
  await signIn(page, 'slow@example.test');
  await expect(page.getByTestId('dlsite-progress')).toContainText('正在登录');
  await shot(page, 'dlsite-signing-in');
  await page.getByTestId('dlsite-progress').getByRole('button', { name: '取消' }).click();
  await expect(page.getByLabel('密码', { exact: true })).toBeVisible();
  await expect(row(page)).toContainText('未连接');
});

test('platform verification is explained and can be cancelled', async ({ page }) => {
  await openPanel(page);
  await signIn(page, 'verify@example.test');
  const verification = page.getByTestId('dlsite-verification');
  await expect(verification).toContainText('只能由你本人完成');
  await expect(verification.getByRole('button', { name: '回到验证窗口' })).toBeVisible();
  await shot(page, 'dlsite-needs-verification');
  await verification.getByRole('button', { name: '取消' }).click();
  await expect(page.getByLabel('密码', { exact: true })).toBeVisible();
});

test('the web login fallback is available and needs no password here', async ({ page }) => {
  await openPanel(page);
  await row(page).getByRole('button', { name: '改用网页登录' }).click();
  await expect(row(page).getByTestId('dlsite-connected')).toBeVisible();
});

test('an unavailable login component points to the web login', async ({ page }) => {
  await openPanel(page);
  await signIn(page, 'changed@example.test');
  await expect(row(page)).toContainText('可以改用网页登录');
  await expect(row(page).getByRole('button', { name: '改用网页登录' })).toBeVisible();
});

test('expired, unverifiable and unstorable sessions are told apart', async ({ page }) => {
  await openPanel(page);
  await signIn(page, 'ok@example.test');
  await expect(row(page).getByTestId('dlsite-connected')).toBeVisible();

  await control({ check: 'unavailable' });
  await row(page).getByRole('button', { name: '重新验证' }).click();
  await expect(row(page)).toContainText('暂时无法验证');
  await expect(row(page)).toContainText('这不代表登录已失效');
  await shot(page, 'dlsite-unverified');

  await control({ check: 'expired' });
  await row(page).getByRole('button', { name: '重新验证' }).click();
  await expect(row(page)).toContainText('会话已过期');
  await expect(row(page)).toContainText('登录已失效');
  await expect(page.getByLabel('密码', { exact: true })).toBeVisible();
  await shot(page, 'dlsite-reauth');

  await control({ store: 'fail-write' });
  await signIn(page, 'ok@example.test');
  await expect(row(page)).toContainText('无法安全保存');
  await expect(row(page)).not.toContainText('已连接');
});

test('a failed cleanup is reported and the session stays disabled', async ({ page }) => {
  await openPanel(page);
  await signIn(page, 'ok@example.test');
  await expect(row(page).getByTestId('dlsite-connected')).toBeVisible();
  await control({ store: 'fail-delete' });
  await row(page).getByRole('button', { name: '退出登录' }).click();
  await expect(row(page)).toContainText('不会再被使用');
  await shot(page, 'dlsite-disconnect-failed');
  await control({});
  await row(page).getByRole('button', { name: '重试退出登录' }).click();
  await expect(row(page)).toContainText('未连接');
});

test('a different account asks first', async ({ page }) => {
  await openPanel(page);
  await signIn(page, 'first@example.test');
  await expect(row(page).getByTestId('dlsite-connected')).toBeVisible();
  await row(page).getByRole('button', { name: '退出登录' }).click();
  await submitLogin(page, 'second@example.test');
  await expect(page.getByTestId('account-mismatch')).toContainText('不是同一个');
  await shot(page, 'dlsite-account-mismatch');
  await expect(row(page)).toContainText('未连接');
  await page.getByRole('button', { name: '确认切换并登录' }).click();
  await expect(row(page).getByTestId('dlsite-connected')).toBeVisible();
});

test('the service being down does not read as signed out', async ({ page }) => {
  await openPanel(page);
  await signIn(page, 'ok@example.test');
  await expect(row(page).getByTestId('dlsite-connected')).toBeVisible();
  await service.stop();
  await expect(page.getByTestId('workspace-indicator')).toHaveText('本地服务未连接', {
    timeout: 20_000,
  });
  await expect(row(page)).toContainText('已连接'); // Last known state stays until told otherwise.
  await service.start();
});

test('the account is in the top bar, masked, with log out', async ({ page }) => {
  await openPanel(page);
  await page.keyboard.press('Escape');
  const menu = page.getByTestId('account-menu');
  await expect(menu).toContainText('登录 DLsite');
  await menu.getByRole('button').first().click();
  await expect(page.getByTestId('account-panel')).toContainText('未连接');
  await page.getByTestId('account-panel').getByRole('button', { name: '登录 DLsite' }).click();
  await signIn(page, 'someone@example.test');
  await expect(row(page).getByTestId('dlsite-connected')).toBeVisible();
  await page.keyboard.press('Escape');

  // The top bar follows a login that finished in the background, without a reload.
  await expect(menu).toContainText('som•••@example.test');
  await expect(page.locator('body')).not.toContainText('someone@example.test');
  await noHorizontalScroll(page);
  await menu.getByRole('button').first().click();
  const panel = page.getByTestId('account-panel');
  await expect(panel).toContainText('已连接');
  await shot(page, 'account-menu');
  await page.keyboard.press('Escape');
  await expect(panel).toHaveCount(0);

  await menu.getByRole('button').first().click();
  await panel.getByRole('button', { name: '退出登录' }).click();
  await expect(menu).toContainText('登录 DLsite');
  await expect(page.getByText('已退出 DLsite 登录')).toBeVisible();
});

test('settings holds the account and the download folders', async ({ page }, info) => {
  const chosen = join(service.dataDir, '..', `chosen ${info.project.name} 文件夹`);
  await mkdir(chosen, { recursive: true });
  await enterRealMode(page);
  await page.goto(`${service.origin}/library`);
  await page.getByRole('link', { name: '设置' }).click();
  await expect(page).toHaveURL(/\/settings$/);
  const settings = page.getByTestId('settings-page');
  await expect(settings.getByRole('heading', { name: '账号' })).toBeVisible();
  await expect(settings.getByLabel('DLsite 账号')).toBeVisible();
  await noHorizontalScroll(page);
  await shot(page, 'settings-page');

  // Choosing through the system dialog (answered by the test stand-in).
  const library = settings.locator('[data-folder="library"]');
  await control({ pick: chosen });
  await library.getByRole('button', { name: '更改' }).click();
  await expect(library.getByLabel('作品文件夹')).toHaveValue(/chosen/);
  await library.getByRole('button', { name: '打开' }).click();
  await expect(library.locator('.dlsite-message')).toHaveCount(0);

  // Typing a path, with a clear refusal for one that does not exist.
  const cache = settings.locator('[data-folder="download_cache"]');
  await cache.getByLabel('下载缓存文件夹').fill(join(chosen, 'does-not-exist'));
  await cache.getByRole('button', { name: '保存' }).click();
  await expect(cache.locator('.dlsite-message')).toContainText('不存在');
  await shot(page, 'settings-folder-error');

  await service.restart();
  await page.reload();
  await expect(settings.locator('[data-folder="library"]').getByLabel('作品文件夹')).toHaveValue(
    /chosen/,
  );
});

test('settings in the demo space stay out of real data', async ({ page }) => {
  const calls: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/api/')) calls.push(request.url());
  });
  await page.goto(`${service.origin}/settings`);
  const settings = page.getByTestId('settings-page');
  await expect(settings).toContainText('演示空间不连接真实账号');
  await expect(settings.getByLabel('密码', { exact: true })).toHaveCount(0);
  await expect(page.getByTestId('account-menu')).toHaveCount(0);
  await shot(page, 'settings-demo');
  expect(calls).toEqual([]);
});

test('a poll that lands after the login cannot bring back the login form', async ({ page }) => {
  await openPanel(page);
  await page.getByLabel('DLsite 账号').fill('ok@example.test');
  await page.getByLabel('密码', { exact: true }).fill(password);
  // Hold one poll that started before the login, with the old answer in it.
  let release = () => {};
  const held = new Promise<void>((done) => (release = done));
  let holding = true;
  await page.route('**/api/v1/sources/dlsite/connection', async (route) => {
    if (holding) {
      holding = false;
      const response = await route.fetch();
      await held;
      await route.fulfill({ response }).catch(() => undefined);
    } else {
      await route.continue();
    }
  });
  await expect.poll(() => holding, { timeout: 15_000 }).toBe(false);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  const confirm = page.getByRole('button', { name: '确认切换并登录' });
  await confirm.or(page.getByTestId('dlsite-connected')).first().waitFor();
  if (await confirm.isVisible()) await confirm.click();
  await expect(row(page).getByTestId('dlsite-connected')).toBeVisible();
  release();
  await page.waitForTimeout(500);
  await expect(row(page).getByTestId('dlsite-connected')).toBeVisible();
  await expect(page.getByLabel('密码', { exact: true })).toHaveCount(0);
});

test('a remembered login is one click and never reaches the page', async ({ page }) => {
  await openPanel(page);
  await page.getByLabel('DLsite 账号').fill('saved@example.test');
  await page.getByLabel('密码', { exact: true }).fill(password);
  await page.getByLabel('记住账号和密码').check();
  await expect(row(page)).toContainText('Windows 凭据管理器');
  await shot(page, 'dlsite-remember');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  const confirm = page.getByRole('button', { name: '确认切换并登录' });
  await confirm.or(page.getByTestId('dlsite-connected')).first().waitFor();
  if (await confirm.isVisible()) await confirm.click();
  await expect(row(page).getByTestId('dlsite-connected')).toBeVisible();
  await row(page).getByRole('button', { name: '退出登录' }).click();

  const saved = page.getByTestId('dlsite-saved-login');
  await expect(saved).toContainText('sav•••@example.test');
  await expect(page.getByLabel('密码', { exact: true })).toHaveCount(0);
  await shot(page, 'dlsite-saved-login');
  expect(await page.content()).not.toContain(password);
  const responses: string[] = [];
  page.on('response', async (response) => {
    if (response.url().includes('/sources/dlsite')) responses.push(await response.text());
  });
  await saved.getByRole('button', { name: '登录', exact: true }).click();
  await expect(row(page).getByTestId('dlsite-connected')).toBeVisible();
  expect(responses.join('\n')).not.toContain(password);

  await service.restart();
  await openPanel(page);
  await row(page).getByRole('button', { name: '退出登录' }).click();
  await expect(saved).toBeVisible();
  await saved.getByRole('button', { name: '忘记保存的密码' }).click();
  await expect(page.getByLabel('密码', { exact: true })).toBeVisible();
  await expect(page.getByTestId('dlsite-saved-login')).toHaveCount(0);
});

test('the demo connection panel never reaches the real flow', async ({ page }) => {
  const calls: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/sources/dlsite')) calls.push(request.url());
  });
  await page.goto(`${service.origin}/`);
  await expect(page.getByTestId('workspace-indicator')).toHaveText('DEMO · 演示模式');
  await page.getByRole('button', { name: '管理来源连接' }).click();
  await expect(page.getByRole('dialog', { name: '来源连接' })).toContainText('Atlas 演示账号');
  await expect(page.getByLabel('密码', { exact: true })).toHaveCount(0);
  expect(calls).toEqual([]);
});
