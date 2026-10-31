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

  test('a scan links what matches by itself, can be undone, and touches no file', async ({
    page,
  }) => {
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
    await panel.getByText('高级选项').click();
    await panel.getByLabel('指定文件夹').fill(library);
    await panel.getByRole('button', { name: '重新扫描并关联' }).click();
    await expect(panel.getByTestId('scan-linked')).toContainText('这次自动关联 3 部', {
      timeout: 20_000,
    });
    await panel.getByRole('tab', { name: /已关联/ }).click();
    await expect(panel.getByTestId('scan-items')).toContainText(works[0].title);
    await panel.getByRole('tab', { name: /没有匹配/ }).click();
    await expect(panel.getByTestId('scan-items')).toContainText('作品库里没有的作品');
    await shot(page, 'scan-results');
    await noHorizontalScroll(page);

    // A folder the scan could not place can be given its work by hand, here in settings.
    const other = (
      await (await call('/works?limit=5&search=' + encodeURIComponent('合成作品'))).json()
    ).items.find((item: { id: string }) => !works.some((w: { id: string }) => w.id === item.id));
    const row = panel.locator('[data-scan-item]').filter({ hasText: '作品库里没有的作品' });
    await row.getByRole('button', { name: '手动选择作品' }).click();
    await row.getByLabel('搜索作品').fill(other.title);
    await shot(page, 'scan-pick');
    await row.getByTestId('scan-pick').getByRole('button', { name: other.title }).click();
    await expect(panel.getByRole('tab', { name: /没有匹配/ })).toContainText('(0)');
    const picked = (await (await call(`/works/${other.id}/local-copies`)).json()).copies;
    expect(picked[0].root).toContain('作品库里没有的作品');

    const copies = (await (await call(`/works/${works[0].id}/local-copies`)).json()).copies;
    expect(copies[0].origin).toBe('scanned');
    expect(copies[0].entry).toBe('Game.exe');

    await panel.getByRole('button', { name: '撤销这次关联' }).click();
    await expect(panel.getByRole('button', { name: /关联 3 部匹配的作品/ })).toBeVisible();
    expect((await (await call(`/works/${works[0].id}/local-copies`)).json()).copies).toEqual([]);
    // Taken back stays taken back: scanning again does not link them behind the user's back.
    await panel.getByRole('button', { name: '重新扫描并关联' }).click();
    await expect(panel.getByTestId('scan-linked')).toContainText('已关联 1 部', {
      timeout: 20_000,
    });
    expect((await (await call(`/works/${works[0].id}/local-copies`)).json()).copies).toEqual([]);
    expect(await readdir(folders[0]!)).toEqual(['Game.exe']);
    expect((await stat(join(folders[0]!, 'Game.exe'))).mtimeMs).toBe(before);
    await shot(page, 'scan-undone');
  });
});
