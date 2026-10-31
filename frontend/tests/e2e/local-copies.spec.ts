import { expect, test, type Page } from '@playwright/test';
import { copyFile, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { noHorizontalScroll, viewportTag } from './evidence';
import { RealService } from './real-service';

/**
 * Real API, database and processes. The "game" is a copy of cmd.exe in a made-up folder, so a real
 * click really starts a real process. No real game is involved.
 */
const evidenceDir = resolve('../artifacts/phase-2-checkpoint-7');
const coreProjects = ['1080p', 'narrow', '4k-200'];
const cmd = join(process.env.SystemRoot ?? 'C:\\Windows', 'System32', 'cmd.exe');

let service: RealService;
let token: string;
let games: string;

async function shot(page: Page, name: string) {
  const info = test.info();
  const dir = resolve(evidenceDir, 'screenshots', info.project.name);
  await mkdir(dir, { recursive: true });
  await page.screenshot({
    path: resolve(dir, `${name}__${viewportTag(page, info)}.png`),
    animations: 'disabled',
    // Test folders sit under the Windows user's own directory.
    mask: [page.locator('#copy-root')],
  });
}

const call = (path: string, method = 'GET', body?: unknown) =>
  fetch(`${service.origin}/api/v1${path}`, {
    method,
    headers: { Origin: service.origin, 'X-Atlas-CSRF': token, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

async function control(values: Record<string, unknown>) {
  await writeFile(join(service.dataDir, 'fake-platform.json'), JSON.stringify(values));
}

interface Work {
  id: string;
  kind: string;
}

let next = 0;
async function work(kind: string): Promise<Work> {
  const page = await (await call(`/works?limit=100&kind=${kind}`)).json();
  return page.items[next++ % page.items.length];
}

async function gameFolder(name: string) {
  const folder = join(games, name);
  await mkdir(join(folder, 'data'), { recursive: true });
  await copyFile(cmd, join(folder, 'Game.exe'));
  return folder;
}

test.describe('local copies', () => {
  test.beforeAll(async () => {
    test.skip(!coreProjects.includes(test.info().project.name), 'core tiers only');
    test.setTimeout(120_000);
    service = await RealService.create(40, 8807);
    await service.start();
    games = join(service.dataDir, '..', 'ゲーム 置き場');
    await rm(games, { recursive: true, force: true });
    await mkdir(games, { recursive: true });
    token = (await (await fetch(`${service.origin}/api/v1/session`)).json()).csrfToken;
  });
  test.afterAll(async () => service?.dispose());
  test('link a folder, start it with a click, and it is still linked after a restart', async ({
    page,
  }) => {
    const game = await work('game');
    const folder = await gameFolder(`a-${test.info().project.name}`);
    await control({ pick: folder });
    await page.goto(`${service.origin}/library/${game.id}`);
    const panel = page.getByTestId('local-copy');
    await panel.getByRole('button', { name: '手动指定文件夹' }).click();
    const form = page.getByTestId('copy-form');
    await form.getByRole('button', { name: '选择' }).click();
    await expect(form.getByLabel('文件夹', { exact: true })).toHaveValue(folder);
    // The one plausible program is suggested, and saving runs nothing.
    await expect(form.getByLabel('主程序', { exact: true })).toHaveValue('Game.exe');
    await form.getByText('高级选项').click();
    await form.getByLabel(/启动参数/).fill('/c\ncd\n>\nran.txt');
    await form.getByLabel(/工作目录/).fill('data');
    await shot(page, 'link-form');
    await noHorizontalScroll(page);
    await form.getByRole('button', { name: '保存' }).click();
    await expect(form).toHaveCount(0);
    expect(await readdir(join(folder, 'data'))).toEqual([]);

    await panel.getByTestId('launch').click();
    await expect(page.getByText('已请求启动')).toBeVisible();
    await expect
      .poll(async () => readFile(join(folder, 'data', 'ran.txt'), 'utf8').catch(() => ''))
      .toContain('data');
    await shot(page, 'linked');

    await service.restart();
    token = (await (await fetch(`${service.origin}/api/v1/session`)).json()).csrfToken;
    await page.reload();
    await expect(panel.getByTestId('launch')).toBeEnabled();
    await panel.getByRole('button', { name: '取消关联' }).click();
    await expect(panel.getByRole('button', { name: '手动指定文件夹' })).toBeVisible();
    expect(await readdir(folder)).toContain('Game.exe');
  });

  test('a program that is gone is explained, and the record stays', async ({ page }) => {
    const game = await work('game');
    const folder = await gameFolder(`b-${test.info().project.name}`);
    await call(`/works/${game.id}/local-copies`, 'POST', { root: folder, entry: 'Game.exe' });
    await rm(join(folder, 'Game.exe'));
    await page.goto(`${service.origin}/library/${game.id}`);
    const panel = page.getByTestId('local-copy');
    await expect(panel.getByTestId('copy-status')).toContainText('主程序不在了');
    // Starting is how the user is asked again. Here nothing is left to choose, and it says so.
    await panel.getByTestId('launch').click();
    await expect(page.getByTestId('choose-none')).toContainText('没有找到可以启动的程序');
    await shot(page, 'entry-missing');
  });

  test('other kinds of work can open their folder but not start', async ({ page }) => {
    const other = await work('audio');
    const folder = await gameFolder(`c-${test.info().project.name}`);
    await call(`/works/${other.id}/local-copies`, 'POST', { root: folder });
    await page.goto(`${service.origin}/library/${other.id}`);
    const panel = page.getByTestId('local-copy');
    await expect(panel.getByRole('button', { name: '打开目录' })).toBeVisible();
    await expect(panel.getByTestId('launch')).toHaveCount(0);
    await expect(panel.getByTestId('copy-status')).toHaveCount(0);
  });

  test('several copies: one default, chosen plainly', async ({ page }) => {
    const game = await work('game');
    const one = await gameFolder(`d1-${test.info().project.name}`);
    const two = await gameFolder(`d2-${test.info().project.name}`);
    await call(`/works/${game.id}/local-copies`, 'POST', {
      root: one,
      entry: 'Game.exe',
      label: 'C 盘',
    });
    await call(`/works/${game.id}/local-copies`, 'POST', {
      root: two,
      entry: 'Game.exe',
      label: 'E 盘',
    });
    await page.goto(`${service.origin}/library/${game.id}`);
    const list = page.getByRole('list', { name: '本地副本' });
    await expect(list.getByRole('button', { name: 'C 盘', exact: true })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await list.getByRole('button', { name: 'E 盘', exact: true }).click();
    await expect(list.getByRole('button', { name: 'E 盘', exact: true })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await shot(page, 'several-copies');
  });
});
