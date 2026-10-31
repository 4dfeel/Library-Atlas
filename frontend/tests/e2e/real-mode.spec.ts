import { expect, test, type Page } from '@playwright/test';
import { resolve } from 'node:path';
import { mkdir, writeFile } from 'node:fs/promises';
import { noHorizontalScroll, viewportTag, watchConsole } from './evidence';
import { modeKey, RealService, enterRealMode } from './real-service';

/** Real service, real database, production build. Synthetic data only; no platform accounts. */
const evidenceDir = resolve('../artifacts/phase-2-checkpoint-1');
const coreProjects = ['1080p', 'narrow', '4k-200'];
const sentinel = /SENTINEL|syn-private|syn-hidden|syn-quarantined/;

async function shot(page: Page, name: string) {
  const info = test.info();
  const dir = resolve(evidenceDir, 'screenshots', info.project.name);
  await mkdir(dir, { recursive: true });
  const path = resolve(dir, `${name}__${viewportTag(page, info)}.png`);
  await page.screenshot({ path, animations: 'disabled' });
}

const indicator = (page: Page) => page.getByTestId('workspace-indicator');

test.describe('empty real library', () => {
  let service: RealService;
  test.beforeAll(async () => {
    test.skip(!coreProjects.includes(test.info().project.name), 'core tiers only');
    service = await RealService.create(null, 8791);
    await service.start();
  });
  test.afterAll(async () => service?.dispose());

  test('shows the truth: empty, not connected, no demo works', async ({ page }) => {
    const console_ = watchConsole(page);
    await enterRealMode(page);
    await page.goto(`${service.origin}/library`);
    await expect(indicator(page)).toHaveText('我的资料库');
    await expect(page.getByText('你的作品库还是空的')).toBeVisible();
    await expect(page.getByTestId('library-results')).toHaveAttribute('data-count', '0');
    await expect(page.locator('[data-game-card]')).toHaveCount(0);
    await expect(page.locator('body')).not.toContainText('DEMO');
    await expect(page.locator('body')).not.toContainText('合成');
    await noHorizontalScroll(page);
    await shot(page, 'real-empty-library');

    await page.getByRole('button', { name: '连接 DLsite' }).click();
    const dialog = page.getByTestId('real-sources');
    await expect(dialog).toContainText('未连接');
    await expect(dialog).not.toContainText('已连接');
    await expect(dialog.getByRole('button', { name: '登录', exact: true })).toBeVisible();
    await shot(page, 'real-sources-not-connected');
    await page.keyboard.press('Escape');

    await page.goto(`${service.origin}/`);
    await expect(page.getByTestId('dashboard-empty')).toContainText('你的作品库还是空的');
    await expect(page.locator('body')).not.toContainText('DEMO');
    await shot(page, 'real-empty-dashboard');
    console_.assert();

    // A demo ID means nothing here (the browser logs the expected 404).
    await page.goto(`${service.origin}/library/demo-00001`);
    await expect(page.getByTestId('game-unavailable')).toBeVisible();

    await page.getByRole('button', { name: '下载任务' }).click();
    await expect(page.getByTestId('downloads-page')).toContainText('队列中没有任务');
  });
});

test.describe('isolated test library', () => {
  let service: RealService;
  test.beforeAll(async () => {
    test.skip(!coreProjects.includes(test.info().project.name), 'core tiers only');
    test.setTimeout(180_000);
    service = await RealService.create(120, 8792);
    await service.start();
  });
  test.afterAll(async () => service?.dispose());

  test('browse, filter, edit, sync across pages and survive a restart', async ({ page }, info) => {
    const suffix = info.project.name;
    const note = `重启后仍在 ${suffix}`;
    await enterRealMode(page);
    await page.goto(`${service.origin}/library`);
    await expect(indicator(page)).toHaveText('测试库 · 合成数据');
    // The toolbar note hides on narrow windows; the top bar label above never does.
    if (page.viewportSize()!.width > 1280)
      await expect(page.getByText('测试数据 · 合成样本，不是同步结果')).toBeVisible();
    await expect(page.getByTestId('library-results')).toHaveAttribute('data-count', '120');
    await expect(page.locator('body')).not.toContainText('DEMO');
    await expect(page.locator('body')).not.toContainText(sentinel);
    await noHorizontalScroll(page);
    await shot(page, 'test-library-grid');

    // Search and filters run on the server.
    await page.getByLabel('搜索作品').fill('同名样本');
    await expect(page.getByTestId('library-results')).toHaveAttribute('data-count', '2');
    await page.getByLabel('平台').selectOption('dlsite');
    await expect(page.getByTestId('library-results')).toHaveAttribute('data-count', '1');
    await page.getByLabel('平台').selectOption('all');
    await page.getByLabel('搜索作品').fill('SENTINEL');
    await expect(page.getByTestId('library-results')).toHaveAttribute('data-count', '0');
    await expect(page.getByText('还没有找到这段冒险')).toBeVisible();
    await page.getByLabel('搜索作品').fill('多文件样本');
    await expect(page.getByTestId('library-results')).toHaveAttribute('data-count', '1');

    // Open the detail through the list, then edit.
    await page.getByRole('link', { name: '多文件样本：群岛航线' }).first().click();
    await expect(page.getByTestId('detail-title')).toHaveText('多文件样本：群岛航线');
    const files = page.getByTestId('work-files');
    await expect(files.locator('li')).toHaveCount(3);
    await expect(files).toContainText('大小未知');
    await expect(page.getByTestId('download-action')).toContainText('下载');
    await expect(page.locator('body')).not.toContainText('DEMO');
    await noHorizontalScroll(page);
    await shot(page, 'test-library-detail');

    await page.getByRole('radio', { name: /进行中/ }).click({ force: true });
    await expect(page.getByTestId('detail-status')).toContainText('进行中');
    await page.getByRole('radio', { name: '4 星' }).click({ force: true });
    await expect(page.locator('.rating-value')).toHaveText('4 / 5');
    await page.getByRole('button', { name: '添加备注' }).click();
    // Stored and shown as plain text.
    await page.locator('.note-input').fill(`<img src=x onerror=alert(1)>${note}`);
    await page.getByRole('button', { name: '保存备注' }).click();
    await expect(page.locator('.note-text')).toContainText(note);
    await expect(page.locator('.note-text img')).toHaveCount(0);
    await page.locator('.hero-actions').getByRole('button', { name: '收藏' }).click();
    await expect(
      page.locator('.hero-actions').getByRole('button', { name: '已收藏' }),
    ).toBeVisible();

    // The Library and Dashboard read the same record without a reload.
    await page.getByTestId('back-to-library').click();
    await expect(page.getByTestId('library-results')).toHaveAttribute('data-count', '1');
    await expect(page.locator('[data-game-card]').first()).toContainText('进行中');
    await page.getByRole('link', { name: '首页', exact: true }).click();
    const favorites = await page.request.get(`${service.origin}/api/v1/dashboard`);
    const totals = (await favorites.json()).totals;
    await expect(page.getByTestId('stat-works')).toContainText(String(totals.works));
    expect(totals.favorites).toBeGreaterThanOrEqual(1);
    await expect(page.locator('body')).not.toContainText(sentinel);
    await shot(page, 'test-library-dashboard');

    // A real restart of the service; the page is reloaded too.
    await service.restart();
    await page.goto(`${service.origin}/library/syn-multipart`);
    await expect(page.getByTestId('detail-status')).toContainText('进行中');
    await expect(page.locator('.rating-value')).toHaveText('4 / 5');
    await expect(page.locator('.note-text')).toContainText(note);
    await expect(
      page.locator('.hero-actions').getByRole('button', { name: '已收藏' }),
    ).toBeVisible();

    // Put the favorite back so later tiers start from the same state.
    await page.locator('.hero-actions').getByRole('button', { name: '已收藏' }).click();
    await expect(page.locator('.hero-actions').getByRole('button', { name: '收藏' })).toBeVisible();
  });

  test('deep link, refresh, back and forward work on the real library', async ({ page }) => {
    await enterRealMode(page);
    await page.goto(`${service.origin}/library/syn-steam-1001`);
    await expect(page.getByTestId('detail-title')).toContainText('同名样本');
    await expect(page.getByText('未提供成就信息')).toHaveCount(0);
    await page.reload();
    await expect(page.getByTestId('detail-title')).toContainText('同名样本');
    await page.getByTestId('back-to-library').click();
    await expect(page.getByTestId('library-results')).toHaveAttribute('data-count', '120');
    await page.goBack();
    await expect(page.getByTestId('detail-title')).toContainText('同名样本');
    await page.goForward();
    await expect(page.getByTestId('library-results')).toHaveAttribute('data-count', '120');
  });

  test('private and absent IDs look the same', async ({ page }) => {
    await enterRealMode(page);
    const texts: string[] = [];
    for (const id of ['syn-private', 'syn-hidden', 'syn-quarantined', 'no-such-work']) {
      await page.goto(`${service.origin}/library/${id}`);
      const shown = page.getByTestId('game-unavailable');
      await expect(shown).toBeVisible();
      texts.push(await shown.innerText());
    }
    expect(new Set(texts).size).toBe(1);
    await expect(page.locator('body')).not.toContainText(sentinel);
  });

  test('unknown fields read as unknown, not as zero or absent', async ({ page }) => {
    await enterRealMode(page);
    await page.goto(`${service.origin}/library/syn-unknown`);
    await expect(page.getByTestId('detail-title')).toHaveText('未知字段样本');
    await expect(page.locator('.hero-install')).toHaveText('本机状态未知');
    await expect(page.locator('body')).toContainText('未提供');
    await expect(page.getByTestId('game-cover').first()).toHaveAttribute(
      'data-cover-kind',
      'missing',
    );
    await expect(page.getByTestId('download-action')).toContainText('大小未知');
    await page.goto(`${service.origin}/library/syn-long-title`);
    await noHorizontalScroll(page);
    await shot(page, 'test-library-long-title');
  });

  test('a failed save keeps the note and says it was not saved', async ({ page }) => {
    await enterRealMode(page);
    await page.goto(`${service.origin}/library/syn-dlsite-1001`);
    await expect(page.getByTestId('detail-title')).toContainText('同名样本');
    await page.getByRole('button', { name: /添加备注|编辑备注/ }).click();
    const draft = '服务中断时写下的备注';
    await page.locator('.note-input').fill(draft);

    await service.stop();
    await page.getByRole('button', { name: '保存备注' }).click();
    await expect(page.locator('.save-error').first()).toContainText('修改尚未保存');
    await expect(page.locator('.note-input')).toHaveValue(draft);
    await expect(page.locator('.save-success')).toHaveCount(0);
    await shot(page, 'test-library-save-failed');

    // The service comes back with a new CSRF token; the same draft saves without re-entry.
    await service.start();
    await page.getByRole('button', { name: '保存备注' }).click();
    await expect(page.locator('.note-text')).toContainText(draft);
    await page.reload();
    await expect(page.locator('.note-text')).toContainText(draft);
    await page.getByRole('button', { name: '编辑备注' }).click();
    await page.locator('.note-input').fill('');
    await page.getByRole('button', { name: '保存备注' }).click();
    await expect(page.locator('.note-empty')).toBeVisible();
  });

  test('an edit from another tab is not silently overwritten', async ({ page, request }) => {
    await enterRealMode(page);
    await page.goto(`${service.origin}/library/syn-steam-1001`);
    await page.getByRole('button', { name: /添加备注|编辑备注/ }).click();
    await page.locator('.note-input').fill('旧页面里的草稿');
    const headers = {
      Origin: service.origin,
      'X-Atlas-CSRF': (await (await request.get(`${service.origin}/api/v1/session`)).json())
        .csrfToken,
    };
    const other = await request.patch(`${service.origin}/api/v1/works/syn-steam-1001/personal`, {
      headers,
      data: { rating: 2 },
    });
    expect(other.ok()).toBe(true);
    await page.getByRole('button', { name: '保存备注' }).click();
    await expect(page.locator('.save-error').first()).toContainText('已在别处更新');
    await expect(page.locator('.note-input')).toHaveValue('旧页面里的草稿');
    // The refreshed record is in place, so saving again is deliberate and succeeds.
    await expect(page.locator('.rating-value')).toHaveText('2 / 5');
    await page.getByRole('button', { name: '保存备注' }).click();
    await expect(page.locator('.note-text')).toContainText('旧页面里的草稿');
    await page.getByRole('button', { name: '编辑备注' }).click();
    await page.locator('.note-input').fill('');
    await page.getByRole('button', { name: '保存备注' }).click();
    await expect(page.locator('.note-empty')).toBeVisible();
  });

  test('service outage shows an outage, never an empty library or demo data', async ({ page }) => {
    await enterRealMode(page);
    // Opening a detail first means its page module is already in memory.
    await page.goto(`${service.origin}/library/syn-steam-1001`);
    await expect(page.getByTestId('detail-title')).toContainText('同名样本');
    await page.getByTestId('back-to-library').click();
    await expect(page.getByTestId('library-results')).toHaveAttribute('data-count', '120');
    await service.stop();
    await page.route('**/*', (route) =>
      route.request().url().includes('/api/') ? route.abort() : route.continue(),
    );
    // A fresh navigation served from the still-loaded app state.
    await page.evaluate(() => {
      window.history.pushState({}, '', '/');
      window.dispatchEvent(new PopStateEvent('popstate'));
    });
    await expect(page.getByTestId('dashboard-failure')).toContainText('本地服务未连接');
    await expect(page.locator('body')).not.toContainText('DEMO');
    await expect(page.locator('body')).not.toContainText('你的作品库还是空的');
    await page.evaluate(() => {
      window.history.pushState({}, '', '/library/syn-unknown');
      window.dispatchEvent(new PopStateEvent('popstate'));
    });
    await expect(page.getByTestId('detail-failure')).toContainText('本地服务未连接');
    await expect(page.getByTestId('game-unavailable')).toHaveCount(0);
    await expect(indicator(page)).toHaveText('本地服务未连接', { timeout: 20_000 });
    await shot(page, 'service-offline');

    await service.start();
    await page.unroute('**/*');
    await page.getByRole('button', { name: '重新连接' }).click();
    await expect(page.getByTestId('detail-title')).toHaveText('未知字段样本');
  });

  test('a page module lost with the service does not blank the app', async ({ page }) => {
    await enterRealMode(page);
    await page.goto(`${service.origin}/library`);
    await expect(page.getByTestId('library-results')).toHaveAttribute('data-count', '120');
    await service.stop();
    await page.evaluate(() => {
      window.history.pushState({}, '', '/library/syn-unknown');
      window.dispatchEvent(new PopStateEvent('popstate'));
    });
    await expect(page.getByTestId('route-failure')).toContainText('这个页面暂时打不开');
    await expect(page.getByRole('navigation', { name: '当前位置' })).toBeVisible();
    await service.start();
    await page.getByRole('button', { name: '重新加载页面' }).click();
    await expect(page.getByTestId('detail-title')).toHaveText('未知字段样本');
  });

  test('switching modes keeps the libraries apart in both directions', async ({ page }) => {
    await page.goto(`${service.origin}/library`);
    // First run in this browser: the demo workspace, clearly labelled.
    await expect(indicator(page)).toHaveText('DEMO · 演示模式');
    await expect(page.getByTestId('library-results')).toHaveAttribute('data-count', '1463');
    const realCalls: string[] = [];
    page.on('request', (request) => {
      if (request.url().includes('/api/')) realCalls.push(request.url());
    });
    await page.locator('[data-game-card]').first().waitFor();
    expect(realCalls).toEqual([]); // Demo needs no service.

    await indicator(page).click();
    await shot(page, 'workspace-switch');
    await page.getByRole('button', { name: /我的资料库/ }).click();
    await page.keyboard.press('Escape');
    await expect(indicator(page)).toHaveText('测试库 · 合成数据');
    await expect(page.getByTestId('library-results')).toHaveAttribute('data-count', '120');
    await expect(page.locator('body')).not.toContainText('DEMO');
    expect(realCalls.length).toBeGreaterThan(0);
    await page.reload();
    await expect(indicator(page)).toHaveText('测试库 · 合成数据');

    // Editing the real library leaves demo storage untouched.
    await page.goto(`${service.origin}/library/syn-dlsite-1001`);
    await page.getByRole('radio', { name: /搁置/ }).click({ force: true });
    await expect(page.getByTestId('detail-status')).toContainText('搁置');
    const storageKeys = await page.evaluate(() => Object.keys(window.localStorage));
    expect(storageKeys.filter((key) => key.includes('demo-edits'))).toEqual([]);

    // On a real work's page, switching leaves the page rather than showing a stale record.
    await indicator(page).click();
    await page.getByRole('button', { name: /演示空间/ }).click();
    await page.keyboard.press('Escape');
    await expect(page).toHaveURL(/\/library$/);
    await expect(page.getByTestId('library-results')).toHaveAttribute('data-count', '1463');
    await expect(page.locator('body')).not.toContainText('syn-');
    await expect(indicator(page)).toHaveText('DEMO · 演示模式');
    // Demo edits stay in the demo.
    await page.goto(`${service.origin}/library/demo-00001`);
    await page.getByRole('radio', { name: /搁置/ }).click({ force: true });
    await expect(page.getByTestId('detail-status')).toContainText('搁置');
    const realWorks = await page.request.get(`${service.origin}/api/v1/works/demo-00001`);
    expect(realWorks.status()).toBe(404);
    const demoInReal = await page.request.get(`${service.origin}/api/v1/works`, {
      params: { search: '赤沙行者' },
    });
    expect((await demoInReal.json()).filteredCount).toBe(0);
  });

  test('a late real response cannot repaint the demo', async ({ page }) => {
    await enterRealMode(page);
    let release = () => {};
    const gate = new Promise<void>((done) => (release = done));
    await page.route('**/api/v1/works?*', async (route) => {
      await gate;
      await route.continue().catch(() => undefined);
    });
    await page.goto(`${service.origin}/library`);
    await expect(page.getByRole('status', { name: '正在读取本地作品库' })).toBeVisible();
    await indicator(page).click();
    await page.getByRole('button', { name: /演示空间/ }).click();
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('library-results')).toHaveAttribute('data-count', '1463');
    release();
    await page.waitForTimeout(400);
    await expect(page.getByTestId('library-results')).toHaveAttribute('data-count', '1463');
    await expect(indicator(page)).toHaveText('DEMO · 演示模式');
    await expect(page.locator('[data-game-card]').first()).toHaveAttribute(
      'data-game-id',
      /^demo-/,
    );
  });
});

test.describe('large synthetic libraries', () => {
  for (const [size, port] of [
    [1500, 8793],
    [5000, 8794],
  ] as const) {
    test(`${size} works: pages load on demand and nothing is skipped`, async ({ page }, info) => {
      test.skip(info.project.name !== '1080p', 'measured once at 1080p');
      test.setTimeout(240_000);
      const service = await RealService.create(size, port);
      try {
        await service.start();
        const apiCalls: { offset: number; bytes: number; ms: number }[] = [];
        page.on('requestfinished', async (request) => {
          const url = new URL(request.url());
          if (url.pathname !== '/api/v1/works') return;
          const body = await (await request.response())?.body();
          apiCalls.push({
            offset: Number(url.searchParams.get('offset')),
            bytes: body?.length ?? 0,
            ms: request.timing().responseEnd,
          });
        });
        await enterRealMode(page);
        const started = Date.now();
        await page.goto(`${service.origin}/library`);
        const results = page.getByTestId('library-results');
        await expect(results).toHaveAttribute('data-count', String(size));
        await page.locator('[data-game-card]').first().waitFor();
        const firstCards = Date.now() - started;
        const scroller = page.getByTestId('library-scroll');
        const mountedAtTop = await page.locator('[data-game-card]').count();
        expect(mountedAtTop).toBeLessThan(80);
        // The first view must not fetch the library in one piece.
        expect(apiCalls.length).toBeLessThanOrEqual(3);
        expect(apiCalls.every((call) => call.bytes < 200_000)).toBe(true);

        // Jump to the very end, as a scrollbar drag would.
        await scroller.evaluate((node) => node.scrollTo({ top: node.scrollHeight }));
        await expect.poll(() => page.locator('[data-game-card]').count()).toBeGreaterThan(0);
        await expect(page.locator('[data-pending-item]')).toHaveCount(0, { timeout: 15_000 });
        // The list may still be redrawing what the jump brought in: wait until it has settled.
        let lastIds: (string | undefined)[] = [];
        await expect
          .poll(async () => {
            lastIds = await page
              .locator('[data-game-card]')
              .evaluateAll((cards) => cards.map((card) => (card as HTMLElement).dataset.gameId));
            return lastIds.length;
          })
          .toBeGreaterThan(0);
        expect(new Set(lastIds).size).toBe(lastIds.length);
        const mountedAtEnd = await page.locator('[data-game-card]').count();
        expect(mountedAtEnd).toBeLessThan(80);
        const offsets = new Set(apiCalls.map((call) => call.offset));
        expect(offsets.size).toBeLessThan(size / 100); // Skipped the pages in between.

        // Walking every page through the API gives each ordinary work exactly once.
        const seen = new Set<string>();
        for (let offset = 0; offset < size; offset += 100) {
          const page_ = await (
            await page.request.get(`${service.origin}/api/v1/works`, {
              params: { offset, limit: 100, sort: 'name-asc' },
            })
          ).json();
          for (const item of page_.items) seen.add(item.id);
        }
        expect(seen.size).toBe(size);

        // Back from a detail restores the position in a paged list.
        const target = page.locator('[data-game-card] a.game-link').first();
        const targetId = await page
          .locator('[data-game-card]')
          .first()
          .getAttribute('data-game-id');
        await target.click();
        const leftAt = size * 0.9; // Near the end; a reset to the top would fail this.
        await expect(page.getByTestId('game-detail')).toHaveAttribute('data-game-id', targetId!);
        await page.goBack();
        await expect(page.getByTestId('library-results')).toHaveAttribute(
          'data-count',
          String(size),
        );
        await expect
          .poll(() => scroller.evaluate((node) => node.scrollTop))
          .toBeGreaterThan(leftAt);
        await expect(page.locator(`[data-game-id="${targetId}"]`)).toBeVisible();
        // Deep in the list the search box is tucked away; the way back is part of the page.
        await page.getByRole('button', { name: '回到顶部' }).click();

        const timings: Record<string, number[]> = { search: [], kind: [] };
        const measure = async (bucket: string, action: () => Promise<void>) => {
          const begin = Date.now();
          await action();
          timings[bucket]!.push(Date.now() - begin);
        };
        // Same method as Phase 1: from the input event to the new count on screen, debounce
        // included, timed inside the page so test-driver round trips do not count.
        for (let round = 0; round < 20; round++) {
          timings.search!.push(
            await page.evaluate(
              (term) => {
                const input = document.querySelector<HTMLInputElement>(
                  'input[aria-label="搜索作品"]',
                )!;
                const results = document.querySelector<HTMLElement>(
                  '[data-testid="library-results"]',
                )!;
                const before = results.dataset.count;
                const setValue = Object.getOwnPropertyDescriptor(
                  HTMLInputElement.prototype,
                  'value',
                )!.set!;
                const begin = performance.now();
                setValue.call(input, term);
                input.dispatchEvent(new Event('input', { bubbles: true }));
                return new Promise<number>((done) => {
                  const check = () => {
                    if (results.dataset.count !== before) done(performance.now() - begin);
                    else requestAnimationFrame(check);
                  };
                  check();
                });
              },
              `档案 ${round + 1}`,
            ),
          );
          await page.getByLabel('搜索作品').fill('');
          await expect(results).toHaveAttribute('data-count', String(size));
        }
        for (const kind of ['游戏', '音声', '全部', '视频', '全部']) {
          await measure('kind', async () => {
            await page
              .getByRole('group', { name: '作品类型' })
              .getByRole('button', { name: new RegExp(`^${kind}`) })
              .click();
            await expect(page.locator('.updating-label')).toHaveCount(0);
          });
        }
        const dashboardMs: number[] = [];
        for (let round = 0; round < 5; round++) {
          const begin = Date.now();
          await page.request.get(`${service.origin}/api/v1/dashboard`, {
            params: { batch: round + 10 },
          });
          dashboardMs.push(Date.now() - begin);
        }
        await page.getByRole('link', { name: '首页', exact: true }).click();
        await expect(page.getByTestId('stat-works')).toContainText(size.toLocaleString('zh-CN'));
        await mkdir(resolve(evidenceDir, 'performance'), { recursive: true });
        await writeFile(
          resolve(evidenceDir, 'performance', `real-mode-${size}.json`),
          JSON.stringify(
            {
              size,
              firstCardsMs: firstCards,
              mountedAtTop,
              mountedAtEnd,
              worksRequests: apiCalls.length,
              pageBytesMax: Math.max(...apiCalls.map((call) => call.bytes)),
              searchMs: timings.search,
              kindSwitchMs: timings.kind,
              dashboardApiMs: dashboardMs,
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

test('demo mode stays the default and needs no service', async ({ page }, info) => {
  test.skip(info.project.name !== '1080p', 'one tier is enough');
  const calls: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/api/')) calls.push(request.url());
  });
  await page.goto('/library');
  await expect(indicator(page)).toHaveText('DEMO · 演示模式');
  await expect(page.getByTestId('library-results')).toHaveAttribute('data-count', '1463');
  expect(await page.evaluate((key) => window.localStorage.getItem(key), modeKey)).toBeNull();
  expect(calls).toEqual([]);
});
