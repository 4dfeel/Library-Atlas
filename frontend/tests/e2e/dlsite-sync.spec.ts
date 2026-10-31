import { expect, test, type Page } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { noHorizontalScroll, viewportTag } from './evidence';
import { RealService } from './real-service';

/**
 * The real service and database, with the platform replaced by the test profile's stand-in.
 * Proves sync rules and the pages; says nothing about real DLsite responses or timing.
 */
const evidenceDir = resolve('../artifacts/phase-2-checkpoint-3');
const coreProjects = ['1080p', 'narrow', '4k-200'];
/** Curated synthetic works already in the seeded test library. */
const seeded = 6;

let service: RealService;

async function shot(page: Page, name: string) {
  const info = test.info();
  const dir = resolve(evidenceDir, 'screenshots', info.project.name);
  await mkdir(dir, { recursive: true });
  await page.screenshot({
    path: resolve(dir, `${name}__${viewportTag(page, info)}.png`),
    animations: 'disabled',
  });
}

async function control(values: Record<string, unknown>) {
  await writeFile(join(service.dataDir, 'fake-platform.json'), JSON.stringify(values));
}

async function connected() {
  const session = await (await fetch(`${service.origin}/api/v1/session`)).json();
  await fetch(`${service.origin}/api/v1/sources/dlsite/login`, {
    method: 'POST',
    headers: {
      Origin: service.origin,
      'X-Atlas-CSRF': session.csrfToken,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ loginId: 'ok@example.test', password: 'x', confirmSwitch: true }),
  });
  await expect
    .poll(
      async () =>
        (await (await fetch(`${service.origin}/api/v1/sources/dlsite/connection`)).json()).state,
    )
    .toBe('connected');
}

async function openPanel(page: Page) {
  await page.goto(`${service.origin}/`);
  await expect(page.getByTestId('workspace-indicator')).toHaveText('测试库 · 合成数据');
  await page.getByRole('button', { name: '管理来源连接' }).click();
  await expect(page.getByTestId('dlsite-sync')).toBeVisible();
}

const panel = (page: Page) => page.getByTestId('dlsite-sync');

async function syncNow(page: Page) {
  await panel(page).getByRole('button', { name: /同步/ }).click();
  await expect(page.getByTestId('sync-result')).toBeVisible({ timeout: 60_000 });
}

test.describe('sync', () => {
  test.beforeAll(async () => {
    test.skip(!coreProjects.includes(test.info().project.name), 'core tiers only');
    test.setTimeout(120_000);
    service = await RealService.create(0, 8796);
    await service.start();
  });
  test.afterAll(async () => service?.dispose());
  test.beforeEach(async () => {
    await control({ size: 30 });
    await connected();
  });

  test('sync, browse, edit, sync again, restart: nothing lost or duplicated', async ({
    page,
  }, info) => {
    await openPanel(page);
    await expect(panel(page)).toContainText('不会下载文件');
    await syncNow(page);
    await expect(page.getByTestId('sync-result')).toContainText('同步完成：共 30 部');
    await noHorizontalScroll(page);
    await shot(page, 'sync-done');

    // Nothing about the sync page itself reports a download or a use.
    await page.keyboard.press('Escape');
    await page.getByRole('link', { name: '作品库', exact: true }).click();
    const results = page.getByTestId('library-results');
    await expect(results).toHaveAttribute('data-count', String(30 + seeded));
    await page.getByLabel('搜索作品').fill('Synthetic Work 7');
    await expect(results).toHaveAttribute('data-count', '1');
    await page.getByLabel('搜索作品').fill('合成作品');
    await expect(results).toHaveAttribute('data-count', '30');
    await shot(page, 'library-real-works');

    // Types come from the source's type code, not from a default per platform.
    await page.getByLabel('平台').selectOption('dlsite');
    const tabs = page.getByRole('group', { name: '作品类型' });
    await tabs.getByRole('button', { name: /^音声/ }).click();
    // Never a flash of zero while it loads: only the old count or the new one.
    await expect(results).toHaveAttribute('data-count', '6');
    await tabs.getByRole('button', { name: /^全部/ }).click();

    await page.getByLabel('搜索作品').fill('合成作品 9 号');
    await expect(results).toHaveAttribute('data-count', '1');
    await page.locator('[data-game-card] a.game-link').first().click();
    const detail = page.getByTestId('game-detail');
    await expect(detail).toContainText('虚构社团');
    await expect(detail).toContainText('在 DLsite 查看');
    await expect(detail).not.toContainText('已下载');
    const note = `第二次同步后仍在 ${info.project.name}`;
    await page.getByRole('button', { name: '添加备注' }).click();
    await page.locator('.note-input').fill(note);
    await page.getByRole('button', { name: '保存备注' }).click();
    await expect(page.locator('.note-text')).toContainText(note);
    await page.getByRole('radio', { name: '4 星' }).click({ force: true });
    await expect(page.locator('.rating-value')).toHaveText('4 / 5');
    await shot(page, 'detail-real-work');
    const url = page.url();

    // The same library again: same count, same edits.
    await control({ size: 30 });
    await page.getByRole('link', { name: '首页', exact: true }).click();
    await page.getByRole('button', { name: '管理来源连接' }).click();
    await syncNow(page);
    await expect(page.getByTestId('sync-result')).toContainText('新增 0，更新 30');
    await page.keyboard.press('Escape');

    await service.restart();
    await page.goto(url);
    await expect(page.locator('.note-text')).toContainText(note);
    await expect(page.locator('.rating-value')).toHaveText('4 / 5');
    await page.goto(`${service.origin}/library`);
    await expect(page.getByTestId('library-results')).toHaveAttribute(
      'data-count',
      String(30 + seeded),
    );
    await page.goto(`${service.origin}/`);
    await expect(page.getByTestId('stat-works')).toContainText(String(30 + seeded));
    // A purchase is not a use: the recent row comes from the curated samples only.
    await shot(page, 'dashboard-real-works');
  });

  test('progress shows real numbers and a sync can be cancelled', async ({ page }) => {
    await control({ size: 650, sync: 'slow' });
    await openPanel(page);
    await panel(page).getByRole('button', { name: /同步/ }).click();
    const progress = page.getByTestId('sync-progress');
    await expect(progress).toContainText('/ 650');
    await shot(page, 'sync-progress');
    await expect(progress).toContainText(/[1-9]00 \/ 650/, { timeout: 20_000 });
    await panel(page).getByRole('button', { name: '取消同步' }).click();
    await expect(page.getByTestId('sync-result')).toContainText('已取消', { timeout: 20_000 });
  });

  test('an expired session stops the sync and keeps the works', async ({ page }) => {
    await control({ size: 150, sync: 'expired', sync_after: 1 });
    await openPanel(page);
    await syncNow(page);
    await expect(page.getByTestId('real-sources')).toContainText('会话已过期');
    await expect(page.getByLabel('密码', { exact: true })).toBeVisible();
    const works = await (await fetch(`${service.origin}/api/v1/works`)).json();
    expect(works.totalVisible).toBeGreaterThanOrEqual(100 + seeded);
    await shot(page, 'sync-session-expired');
  });

  test('network trouble is partial, keeps the login and can be retried', async ({ page }) => {
    await control({ size: 150, sync: 'offline', sync_after: 1 });
    await openPanel(page);
    await syncNow(page);
    const result = page.getByTestId('sync-result');
    await expect(result).toContainText('暂时连不上 DLsite');
    await expect(result).toContainText('已保存 100 部');
    await expect(page.getByTestId('dlsite-connected')).toBeVisible();
    await shot(page, 'sync-partial');
    await control({ size: 150 });
    await syncNow(page);
    await expect(page.getByTestId('sync-result')).toContainText('同步完成：共 150 部');
  });

  test('a changed response stops and is not called an empty library', async ({ page }) => {
    await control({ size: 30, sync: 'changed' });
    await openPanel(page);
    await syncNow(page);
    const result = page.getByTestId('sync-result');
    await expect(result).toContainText('和预期不同');
    await expect(result).not.toContainText('同步完成');
  });

  test('state stays the same across pages and after a restart', async ({ page }) => {
    await control({ size: 30 });
    await openPanel(page);
    await syncNow(page);
    await page.keyboard.press('Escape');
    await page.getByRole('link', { name: '设置' }).click();
    await expect(page.getByTestId('sync-result')).toContainText('同步完成');
    await service.restart();
    await page.reload();
    await expect(page.getByTestId('sync-result')).toContainText('同步完成');
    await expect(panel(page)).toContainText('上次完整同步');
  });

  test('the list view sorts on the server and keeps unknown sizes last', async ({ page }) => {
    await control({ size: 30 });
    await openPanel(page);
    await syncNow(page);
    await page.keyboard.press('Escape');
    await page.goto(
      `${service.origin}/library?view=list&platform=dlsite&q=${encodeURIComponent('合成作品')}`,
    );
    const heading = page.getByRole('group', { name: '按栏目排序' });
    await expect(page.locator('.list-size').first()).toBeVisible();
    await shot(page, 'library-list-columns');
    await heading.getByRole('button', { name: /按大小排序/ }).click();
    await expect(page).toHaveURL(/sort=size-desc/);
    // Earlier tests in this service may have synced more works, so no fixed largest size.
    const firstSize = page.locator('.list-size').first();
    await expect(firstSize).toHaveText(/\d (MB|GB)$/);
    const largest = (await firstSize.textContent())!;
    await heading.getByRole('button', { name: /按大小排序/ }).click();
    await expect(page).toHaveURL(/sort=size-asc/);
    await expect(firstSize).not.toHaveText(largest);
    await expect(firstSize).not.toHaveText('—');
    const scroller = page.getByTestId('library-scroll');
    await scroller.evaluate((node) => node.scrollTo({ top: node.scrollHeight }));
    await expect(page.locator('.list-size').last()).toHaveText('—');
    await expect(page.locator('body')).not.toContainText('NaN');
  });
});

test.describe('scale', () => {
  for (const [size, port] of [
    [1500, 8797],
    [5000, 8798],
  ] as const) {
    test(`${size} synthetic purchases`, async ({ page }, info) => {
      test.skip(info.project.name !== '1080p', 'measured once at 1080p');
      test.setTimeout(240_000);
      service = await RealService.create(0, port);
      try {
        await service.start();
        await control({ size });
        await connected();
        await openPanel(page);
        const begin = Date.now();
        await syncNow(page);
        const firstSync = Date.now() - begin;
        await expect(page.getByTestId('sync-result')).toContainText(
          `共 ${size.toLocaleString('zh-CN')} 部`,
        );
        // The previous result stays on screen, so wait for the new job itself to end.
        const job = async () =>
          (await (await fetch(`${service.origin}/api/v1/sources/dlsite/sync`)).json()).job;
        const firstJob = (await job()).id;
        const repeat = Date.now();
        await panel(page).getByRole('button', { name: /同步/ }).click();
        await expect
          .poll(
            async () => {
              const current = await job();
              return current.id !== firstJob && current.state === 'succeeded';
            },
            { timeout: 120_000 },
          )
          .toBe(true);
        const repeatSync = Date.now() - repeat;
        await page.keyboard.press('Escape');
        await page.getByRole('link', { name: '作品库', exact: true }).click();
        const results = page.getByTestId('library-results');
        await expect(results).toHaveAttribute('data-count', String(size + seeded));
        const mounted = await page.locator('[data-game-card]').count();
        expect(mounted).toBeLessThan(80);
        const search: number[] = [];
        for (let round = 0; round < 10; round++) {
          search.push(
            await page.evaluate(
              (term) => {
                const input = document.querySelector<HTMLInputElement>(
                  'input[aria-label="搜索作品"]',
                )!;
                const out = document.querySelector<HTMLElement>('[data-testid="library-results"]')!;
                const before = out.dataset.count;
                const set = Object.getOwnPropertyDescriptor(
                  HTMLInputElement.prototype,
                  'value',
                )!.set!;
                const start = performance.now();
                set.call(input, term);
                input.dispatchEvent(new Event('input', { bubbles: true }));
                return new Promise<number>((done) => {
                  const check = () =>
                    out.dataset.count !== before
                      ? done(performance.now() - start)
                      : requestAnimationFrame(check);
                  check();
                });
              },
              `合成作品 ${round + 1}0`,
            ),
          );
          await page.getByLabel('搜索作品').fill('');
          await expect(results).toHaveAttribute('data-count', String(size + seeded));
        }
        await mkdir(resolve(evidenceDir, 'performance'), { recursive: true });
        await writeFile(
          resolve(evidenceDir, 'performance', `sync-${size}.json`),
          JSON.stringify(
            {
              size,
              note: 'Stand-in platform with the normal pause between batches. Not DLsite timing.',
              firstSyncMs: firstSync,
              repeatSyncMs: repeatSync,
              mountedCards: mounted,
              searchMs: search,
            },
            null,
            2,
          ),
        );
      } finally {
        await service.dispose();
      }
    });
  }
});
