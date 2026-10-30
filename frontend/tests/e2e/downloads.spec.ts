import { expect, test, type Page } from '@playwright/test';
import { mkdir, readdir, rm, stat, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { noHorizontalScroll, viewportTag } from './evidence';
import { enterRealMode, RealService } from './real-service';

/**
 * The real service and queue, with real sockets and real files. Only the platform is the
 * test profile's stand-in: this proves Atlas's handling, not how DLsite really behaves.
 */
const evidenceDir = resolve('../artifacts/phase-2-checkpoint-4');
const coreProjects = ['1080p', 'narrow', '4k-200'];
const MB = 1024 * 1024;

let service: RealService;
let library: string;
let token: string;
let controlValues: Record<string, unknown> = {};

async function shot(page: Page, name: string) {
  const info = test.info();
  const dir = resolve(evidenceDir, 'screenshots', info.project.name);
  await mkdir(dir, { recursive: true });
  await page.screenshot({
    path: resolve(dir, `${name}__${viewportTag(page, info)}.png`),
    animations: 'disabled',
    // Test folders sit under the Windows user's own directory.
    mask: [page.locator('.download-path')],
  });
}

async function control(values: Record<string, unknown>) {
  controlValues = { ...controlValues, ...values };
  await writeFile(join(service.dataDir, 'fake-platform.json'), JSON.stringify(controlValues));
}

const behave = (download: Record<string, unknown>) => control({ download });

async function call(path: string, method = 'GET', body?: unknown) {
  return fetch(`${service.origin}/api/v1${path}`, {
    method,
    headers: {
      Origin: service.origin,
      'X-Atlas-CSRF': token,
      'Content-Type': 'application/json',
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

async function connectAndSync() {
  token = (await (await fetch(`${service.origin}/api/v1/session`)).json()).csrfToken;
  await control({ size: 40 });
  await call('/sources/dlsite/login', 'POST', { loginId: 'ok@example.test', password: 'x' });
  await expect
    .poll(async () => (await (await call('/sources/dlsite/connection')).json()).state)
    .toBe('connected');
  await call('/sources/dlsite/sync', 'POST');
  await expect
    .poll(async () => (await (await call('/sources/dlsite/sync')).json()).job?.state, {
      timeout: 30_000,
    })
    .toBe('succeeded');
}

interface Work {
  id: string;
  sourceId: string;
}

/** A work no earlier test has touched, so tests stay independent of each other. */
let nextWork = 0;
async function freshWork(): Promise<Work> {
  const page = await (
    await call('/works?limit=100&search=' + encodeURIComponent('合成作品'))
  ).json();
  return page.items[nextWork++ % page.items.length];
}

async function openWork(page: Page, work: Work) {
  await page.goto(`${service.origin}/library/${encodeURIComponent(work.id)}`);
  await expect(page.getByTestId('download-action')).toBeVisible();
}

const action = (page: Page) => page.getByTestId('download-action');

test.describe('downloads', () => {
  test.beforeAll(async () => {
    test.skip(!coreProjects.includes(test.info().project.name), 'core tiers only');
    test.setTimeout(120_000);
    service = await RealService.create(0, 8805);
    await service.start();
    library = join(service.dataDir, '..', '作品 フォルダ');
    await rm(library, { recursive: true, force: true });
    await mkdir(library, { recursive: true });
    await connectAndSync();
    nextWork = 0;
  });
  test.afterAll(async () => service?.dispose());
  test.beforeEach(async ({ page }) => {
    await enterRealMode(page);
    await behave({});
    const put = await call('/settings/folders/library', 'PUT', { path: library });
    expect(put.status).toBe(200);
  });

  test('from the button to a file on disk, and still known after a restart', async ({ page }) => {
    // Slow enough that it is still running after the page reloads below.
    await behave({ mode: 'slow', size: 24 * MB, delay: 0.03 });
    const work = await freshWork();
    await openWork(page, work);
    await shot(page, 'download-ready');
    await action(page).getByRole('button', { name: '下载', exact: true }).click();

    // The transfer is the service's: progress is real bytes, and survives leaving the page.
    const bar = action(page).getByRole('progressbar');
    await expect(bar).toBeVisible();
    await expect(bar).toHaveAttribute('aria-valuenow', /\d+/);
    await shot(page, 'download-progress');
    await page.reload();
    await expect(action(page).getByRole('progressbar')).toBeVisible();

    await expect(action(page).getByTestId('download-done')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText('已安装', { exact: true })).toHaveCount(0);
    await expect(action(page)).toContainText('解压将在后续版本开放');
    await shot(page, 'download-done');
    const folder = join(library, work.sourceId);
    expect(await readdir(folder)).toEqual([`${work.sourceId}.zip`]);
    expect((await stat(join(folder, `${work.sourceId}.zip`))).size).toBe(24 * MB);

    await service.restart();
    token = (await (await fetch(`${service.origin}/api/v1/session`)).json()).csrfToken;
    await page.goto(`${service.origin}/library/${encodeURIComponent(work.id)}`);
    await expect(action(page).getByTestId('download-done')).toBeVisible();
    await expect(page.getByText('已下载').first()).toBeVisible();
  });

  test('a split work asks which files, and only those are fetched', async ({ page }) => {
    await behave({ parts: 3, size: MB });
    const work = await freshWork();
    await openWork(page, work);
    await action(page).getByRole('button', { name: '下载', exact: true }).click();
    const plan = page.getByTestId('download-plan');
    await expect(plan).toBeVisible();
    await expect(plan).toContainText('分成 3 个文件');
    await shot(page, 'download-parts');
    await noHorizontalScroll(page);
    await plan.getByRole('checkbox', { name: '第 2 个文件' }).uncheck();
    await plan.getByRole('button', { name: '开始下载' }).click();
    await expect(plan).toBeHidden();
    await expect(action(page).getByTestId('download-done')).toBeVisible({ timeout: 20_000 });
    expect((await readdir(join(library, work.sourceId))).sort()).toEqual([
      `${work.sourceId}.part1.rar`,
      `${work.sourceId}.part3.rar`,
    ]);
  });

  test('no folder yet: asks once, then downloads', async ({ page }) => {
    await behave({ size: MB });
    const work = await freshWork();
    await call('/settings/folders/library', 'PUT', { path: library });
    // Choose a different folder through the dialog, as the user would.
    const chosen = join(service.dataDir, '..', '选的 文件夹');
    await mkdir(chosen, { recursive: true });
    await control({ pick: chosen });
    await rm(library, { recursive: true, force: true });
    await openWork(page, work);
    await action(page).getByRole('button', { name: '下载', exact: true }).click();
    const plan = page.getByTestId('download-plan');
    await expect(plan).toContainText('现在不存在');
    await expect(plan.getByRole('button', { name: '开始下载' })).toBeDisabled();
    await shot(page, 'download-folder-missing');
    await plan.getByRole('button', { name: /更改文件夹/ }).click();
    await expect(plan.getByRole('button', { name: '开始下载' })).toBeEnabled();
    await plan.getByRole('button', { name: '开始下载' }).click();
    await expect(action(page).getByTestId('download-done')).toBeVisible({ timeout: 20_000 });
    expect(await readdir(join(chosen, work.sourceId))).toEqual([`${work.sourceId}.zip`]);
    await mkdir(library, { recursive: true });
  });

  test('a login page is reported, not saved, and retrying works', async ({ page }) => {
    await behave({ mode: 'login_page' });
    const work = await freshWork();
    await openWork(page, work);
    await action(page).getByRole('button', { name: '下载', exact: true }).click();
    await expect(action(page)).toContainText('不是文件', { timeout: 15_000 });
    await shot(page, 'download-failed');
    await expect
      .poll(async () => readdir(join(library, work.sourceId)).catch(() => [] as string[]))
      .toEqual([]);
    await behave({ size: MB });
    await action(page).getByRole('button', { name: '重新下载' }).click();
    await expect(action(page).getByTestId('download-done')).toBeVisible({ timeout: 20_000 });
  });

  test('the queue: pause, resume, cancel, and one task per file', async ({ page }) => {
    await behave({ mode: 'slow', size: 16 * MB, delay: 0.03 });
    const work = await freshWork();
    await openWork(page, work);
    await action(page).getByRole('button', { name: '下载', exact: true }).click();
    await expect(action(page).getByRole('progressbar')).toBeVisible();
    // A second click from anywhere cannot make a second task.
    const again = await call('/downloads', 'POST', { workId: work.id });
    expect(
      (await again.json()).tasks.filter((t: Work & { workId: string }) => t.workId === work.id),
    ).toHaveLength(1);

    await page.getByRole('button', { name: /下载任务/ }).click();
    const dialog = page.getByRole('dialog', { name: '下载' });
    const row = dialog.locator('[data-download-task]').filter({ hasText: '下载中' }).first();
    await expect(row).toBeVisible({ timeout: 10_000 });
    await shot(page, 'download-queue');
    await noHorizontalScroll(page);
    await row.getByRole('button', { name: '暂停' }).click();
    const paused = dialog.locator('[data-download-task]').filter({ hasText: '已暂停' }).first();
    await expect(paused).toBeVisible();
    await expect(paused.getByRole('button', { name: '继续' })).toBeVisible();
    await paused.getByRole('button', { name: '继续' }).click();
    await expect(dialog.getByText('下载中').first()).toBeVisible();
    await dialog.getByRole('button', { name: '取消' }).first().click();
    await expect(dialog.getByText('已取消').first()).toBeVisible({ timeout: 10_000 });
    await expect
      .poll(async () => readdir(join(library, work.sourceId)).catch(() => [] as string[]))
      .toEqual([]);
    await dialog.getByRole('button', { name: /清除/ }).click();
    await expect(dialog.getByText('已取消')).toHaveCount(0);
  });

  test('a restart in the middle says interrupted and sends nothing by itself', async ({ page }) => {
    await behave({ mode: 'slow', size: 16 * MB, delay: 0.03 });
    const work = await freshWork();
    await openWork(page, work);
    await action(page).getByRole('button', { name: '下载', exact: true }).click();
    await expect(action(page).getByRole('progressbar')).toBeVisible();
    await service.restart();
    token = (await (await fetch(`${service.origin}/api/v1/session`)).json()).csrfToken;
    await behave({ size: 16 * MB });
    await page.reload();
    await expect(action(page)).toContainText('被中断', { timeout: 15_000 });
    await shot(page, 'download-interrupted');
    await expect(action(page).getByRole('button', { name: /继续下载|重新下载/ })).toBeVisible();
    await action(page)
      .getByRole('button', { name: /继续下载|重新下载/ })
      .click();
    await expect(action(page).getByTestId('download-done')).toBeVisible({ timeout: 30_000 });
    expect((await stat(join(library, work.sourceId, `${work.sourceId}.zip`))).size).toBe(16 * MB);
  });

  test('progress does not disturb a note being written or the list', async ({ page }) => {
    await behave({ mode: 'slow', size: 8 * MB, delay: 0.03 });
    const work = await freshWork();
    await openWork(page, work);
    await action(page).getByRole('button', { name: '下载', exact: true }).click();
    await page.getByRole('button', { name: '添加备注' }).click();
    const note = page.locator('textarea').first();
    await note.fill('写到一半的备注');
    await expect(action(page).getByTestId('download-done')).toBeVisible({ timeout: 30_000 });
    await expect(note).toHaveValue('写到一半的备注');

    await page.goto(`${service.origin}/library?view=list`);
    await expect(page.locator('[data-game-card]').first()).toBeVisible();
    await noHorizontalScroll(page);
  });
});
