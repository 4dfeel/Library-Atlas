import { expect, test, type Page } from '@playwright/test';
import { copyFile, mkdir } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { noHorizontalScroll, viewportTag } from './evidence';
import { enterRealMode, RealService } from './real-service';

/**
 * A real launch of a real program, followed by a real job, through the real page. The program is a
 * copy of Windows' own `ping`, which waits a moment and exits: it is no game, and nothing else runs.
 */
const evidenceDir = resolve('../artifacts/play-record');
const coreProjects = ['1080p', 'narrow', '4k-200'];

let service: RealService;
let token: string;

async function shot(page: Page, name: string) {
  const info = test.info();
  const dir = resolve(evidenceDir, 'screenshots', info.project.name);
  await mkdir(dir, { recursive: true });
  await page.screenshot({
    path: resolve(dir, `${name}__${viewportTag(page, info)}.png`),
    animations: 'disabled',
  });
}

const call = (path: string, method = 'GET', body?: unknown) =>
  fetch(`${service.origin}/api/v1${path}`, {
    method,
    headers: { Origin: service.origin, 'X-Atlas-CSRF': token, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

test.describe('recording play', () => {
  test.beforeAll(async () => {
    test.skip(!coreProjects.includes(test.info().project.name), 'core tiers only');
    test.setTimeout(120_000);
    service = await RealService.create(60, 8816);
    await service.start();
    token = (await (await fetch(`${service.origin}/api/v1/session`)).json()).csrfToken;
  });
  test.afterAll(async () => service?.dispose());
  test.beforeEach(async ({ page }) => {
    await enterRealMode(page);
  });

  test('nothing yet says why, then a start is timed from launch to exit and shows everywhere', async ({
    page,
  }) => {
    await page.goto(`${service.origin}/activity`);
    await expect(page.getByTestId('activity-empty')).toContainText('从 Atlas 启动');
    await shot(page, 'activity-empty');

    const listed = await (await call('/works?limit=100&platform=dlsite&kind=game')).json();
    const work = listed.items[0];
    const folder = join(service.dataDir, '..', `合成 ${test.info().project.name}`);
    await mkdir(folder, { recursive: true });
    await copyFile('C:\\Windows\\System32\\PING.EXE', join(folder, 'Game.exe'));
    await call(`/works/${work.id}/local-copies`, 'POST', {
      root: folder,
      entry: 'Game.exe',
      arguments: ['-n', '4', '127.0.0.1'],
    });

    await page.goto(`${service.origin}/library/${work.id}`);
    await page.getByTestId('launch').click();
    await expect(page.getByTestId('play-running')).toBeVisible({ timeout: 15_000 });
    await shot(page, 'play-running');
    await expect(page.getByTestId('play-running')).toHaveCount(0, { timeout: 30_000 });
    await page.getByTestId('play-open').click();
    await expect(page.getByTestId('play-sessions').locator('tr')).toHaveCount(1);
    await expect(page.getByTestId('play-sessions')).not.toContainText('估算');
    await shot(page, 'play-sessions');
    await page.keyboard.press('Escape');

    await expect(page.locator('.hero-facts')).toContainText('累计游玩');
    await expect(page.locator('.hero-facts')).toContainText('最近游玩');

    await page.getByRole('link', { name: '游玩记录' }).first().click();
    const totals = page.getByTestId('activity-totals');
    await expect(totals).toBeVisible();
    await expect(page.getByTestId('activity-recent')).toContainText(work.title);
    await expect(page.getByTestId('activity-month-table')).toContainText(work.title);
    await expect(page.getByTestId('play-bars').getByRole('button')).toHaveCount(12);
    await shot(page, 'activity');
    await noHorizontalScroll(page);
    await page.getByTestId('activity-recent').getByRole('link', { name: work.title }).click();
    await expect(page).toHaveURL(new RegExp(`/library/${work.id}$`));
  });
});
