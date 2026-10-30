import { expect, test, type Page } from '@playwright/test';
import { mkdir, readdir, rm, stat, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { noHorizontalScroll, viewportTag } from './evidence';
import { enterRealMode, RealService } from './real-service';

/** Real API and database, real folders on disk. All names and works are made up. */
const evidenceDir = resolve('../artifacts/phase-2-checkpoint-8');
const coreProjects = ['1080p', 'narrow', '4k-200'];

let service: RealService;
let token: string;
let base: string;

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

const call = (path: string, method = 'GET', body?: unknown) =>
  fetch(`${service.origin}/api/v1${path}`, {
    method,
    headers: { Origin: service.origin, 'X-Atlas-CSRF': token, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

test.describe('finding works on this computer', () => {
  test.beforeAll(async () => {
    test.skip(!coreProjects.includes(test.info().project.name), 'core tiers only');
    test.setTimeout(120_000);
    service = await RealService.create(0, 8808);
    await service.start();
    base = join(service.dataDir, '..', '盘');
    await rm(base, { recursive: true, force: true });
    token = (await (await fetch(`${service.origin}/api/v1/session`)).json()).csrfToken;
    await writeFile(join(service.dataDir, 'fake-platform.json'), JSON.stringify({ size: 12 }));
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
  });
  test.afterAll(async () => service?.dispose());

  test('scan, accept the matches, undo, and no file is touched', async ({ page }) => {
    await enterRealMode(page);
    const library = join(base, test.info().project.name, 'Library');
    const works = (
      await (await call('/works?limit=3&search=' + encodeURIComponent('合成作品'))).json()
    ).items;
    const folders = [];
    for (const work of works) {
      const folder = join(library, 'Game', '虚构社团', work.title);
      await mkdir(folder, { recursive: true });
      await writeFile(join(folder, 'Game.exe'), 'not run');
      folders.push(folder);
    }
    await mkdir(join(library, 'Game', '别的社团', '作品库里没有的作品'), { recursive: true });
    const before = (await stat(join(folders[0]!, 'Game.exe'))).mtimeMs;

    await page.goto(`${service.origin}/settings`);
    const panel = page.getByTestId('library-scan');
    await panel.getByLabel('指定文件夹').fill(library);
    await panel.getByRole('button', { name: '发现本机作品库' }).click();
    const accept = panel.getByRole('button', { name: /关联 3 部匹配的作品/ });
    await expect(accept).toBeVisible({ timeout: 20_000 });
    await expect(panel.getByTestId('scan-items')).toContainText(works[0].title);
    await panel.getByRole('tab', { name: /没有匹配/ }).click();
    await expect(panel.getByTestId('scan-items')).toContainText('作品库里没有的作品');
    await shot(page, 'scan-results');
    await noHorizontalScroll(page);

    await panel.getByRole('tab', { name: /很可能/ }).click();
    await accept.click();
    await expect(panel).toContainText('已关联 3 部');
    const copies = (await (await call(`/works/${works[0].id}/local-copies`)).json()).copies;
    expect(copies[0].origin).toBe('scanned');
    expect(copies[0].entry).toBe('Game.exe');

    await panel.getByRole('button', { name: '撤销这次关联' }).click();
    await expect(panel.getByRole('button', { name: /关联 3 部匹配的作品/ })).toBeVisible();
    expect((await (await call(`/works/${works[0].id}/local-copies`)).json()).copies).toEqual([]);
    expect(await readdir(folders[0]!)).toEqual(['Game.exe']);
    expect((await stat(join(folders[0]!, 'Game.exe'))).mtimeMs).toBe(before);
    await shot(page, 'scan-undone');
  });
});
