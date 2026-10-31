import { expect, test, type Page } from '@playwright/test';
import {
  appOrigin,
  noHorizontalScroll,
  noPrivateData,
  recordLayout,
  screenshot,
  watchConsole,
  writeEvidence,
} from './evidence';

/** Phase 1 checkpoint 4: cross-page acceptance not owned by a single page spec. */

const cards = (page: Page) => page.locator('[data-game-card]');
const results = (page: Page) => page.getByTestId('library-results');

test('static assets load from the local server only, with the outside network blocked', async ({
  browser,
}, info) => {
  test.skip(!['1080p', '4k-200'].includes(info.project.name), 'Checked at DPR 1 and 2.');
  // Fresh context: no HTTP cache, no storage. Everything off the preview origin is aborted.
  const context = await browser.newContext({
    viewport: info.project.use.viewport!,
    deviceScaleFactor: info.project.use.deviceScaleFactor!,
    colorScheme: 'dark',
    reducedMotion: 'reduce',
    locale: 'zh-CN',
    timezoneId: 'Asia/Tokyo',
  });
  const blocked: string[] = [];
  await context.route('**/*', (route) => {
    const url = route.request().url();
    if (url.startsWith(`${appOrigin}/`) || url.startsWith('data:')) return route.continue();
    blocked.push(url);
    return route.abort('internetdisconnected');
  });
  const page = await context.newPage();
  const errors = watchConsole(page);
  const local: { path: string; status: number; type: string }[] = [];
  const failed: string[] = [];
  page.on('response', (response) => {
    const url = new URL(response.url());
    if (url.origin === appOrigin)
      local.push({
        path: url.pathname,
        status: response.status(),
        type: response.request().resourceType(),
      });
  });
  page.on('requestfailed', (request) => failed.push(request.url()));

  const visits = [
    { url: '/', ready: '[data-testid="featured"]' },
    { url: '/?scope=dlsite-media', ready: '[data-testid="featured"]' },
    { url: '/library', ready: '[data-game-card]' },
    { url: '/library?view=list&kind=audio&sort=name-asc', ready: '[data-game-card]' },
    { url: '/library/syn-steam-1001', ready: '[data-testid="detail-title"]' },
    { url: '/library/syn-multipart', ready: '[data-testid="detail-title"]' },
    { url: '/library/syn-long-title', ready: '[data-testid="detail-title"]' },
    { url: '/somewhere-else', ready: 'main' },
  ];
  const pages = [];
  for (const visit of visits) {
    await page.goto(visit.url);
    await expect(page.locator(visit.ready).first()).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    await page.waitForFunction(() => [...document.images].every((image) => image.complete));
    const state = await page.evaluate(() => ({
      cjkFont: document.fonts.check('16px "Noto Sans SC Variable"', '作品库'),
      brokenImages: [...document.images]
        .filter((image) => image.naturalWidth === 0)
        .map((image) => image.getAttribute('alt')),
      images: document.images.length,
    }));
    expect(state.cjkFont).toBe(true);
    expect(state.brokenImages).toEqual([]);
    await noHorizontalScroll(page);
    pages.push({ url: visit.url, ...state });
  }
  // Client-side navigation into a lazy route after the first load.
  await page.goto('/library');
  await cards(page).first().locator('.game-link').click();
  await expect(page.getByTestId('detail-title')).toBeVisible();
  await page.getByRole('link', { name: '首页' }).click();
  await expect(page.getByTestId('featured')).toBeVisible();

  expect(blocked).toEqual([]);
  expect(failed).toEqual([]);
  expect(local.filter((entry) => entry.status >= 400)).toEqual([]);
  errors.assert();
  const byType: Record<string, number> = {};
  for (const entry of local) byType[entry.type] = (byType[entry.type] ?? 0) + 1;
  await writeEvidence(info, `offline-${info.project.name}.json`, {
    method:
      'Fresh browser context (no HTTP cache or storage); every request not to the local preview origin is aborted; data: URIs allowed.',
    scope: 'Requires the local server to be running; not a standalone offline/PWA mode.',
    blockedExternalRequests: blocked,
    failedRequests: failed,
    localResponsesByType: byType,
    fontFiles: [...new Set(local.filter((e) => e.type === 'font').map((e) => e.path))],
    pages,
  });
});

test('no console errors or unhandled rejections across the core flows', async ({ page }, info) => {
  test.skip(!['1080p', 'narrow'].includes(info.project.name), 'Checked at 1080P/720P.');
  // The one address below that does not exist: the browser reports its 404 by itself.
  const errors = watchConsole(page, [/status of 404/]);
  await page.goto('/');
  await expect(page.getByTestId('featured')).toBeVisible();
  await page.locator('.scope-switch').getByRole('button', { name: 'DLsite 其他作品' }).click();
  await expect(page.getByTestId('dashboard')).toHaveAttribute('data-ready', 'true');
  await page.getByRole('button', { name: '换一批' }).click();
  await page.getByRole('button', { name: '管理来源连接' }).click();
  await page.keyboard.press('Escape');
  await page.getByRole('link', { name: '作品库' }).first().click();
  await expect(cards(page).first()).toBeVisible();
  await page.getByRole('textbox', { name: '搜索作品' }).fill('星');
  await page.getByRole('button', { name: '列表视图' }).click();
  await page.getByRole('combobox', { name: '排序' }).selectOption('playtime-desc');
  await cards(page).first().locator('.game-link, a').first().click();
  await expect(page.getByTestId('detail-title')).toBeVisible();
  await page.goBack();
  await expect(cards(page).first()).toBeVisible();
  await page.getByRole('button', { name: /下载任务/ }).click();
  await expect(page).toHaveURL(/\/downloads$/);
  await page.goto('/library/syn-99999');
  await expect(page.getByTestId('game-unavailable')).toBeVisible();
  errors.assert();
});

test('shell: sidebar, route highlight, history and direct detail links', async ({ page }, info) => {
  test.skip(!['1080p', 'narrow'].includes(info.project.name), 'Checked at 1080P/720P.');
  const sidebar = page.getByRole('complementary', { name: '主导航' });
  await page.goto('/library/syn-multipart');
  await expect(page.getByTestId('detail-title')).toBeVisible();
  // A direct detail URL has a real link back to the Library, not history.back().
  await expect(page.getByTestId('back-to-library')).toHaveAttribute('href', '/library');
  await expect(sidebar.getByRole('link', { name: '作品库' })).toHaveClass(/active/);
  const toggle = page.getByRole('button', { name: /侧栏/ });
  if (info.project.name === 'narrow') {
    // At 1280 px the sidebar collapses automatically and stays icon-only.
    await expect(page.locator('.app-shell')).toHaveClass(/sidebar-collapsed/);
    await expect(toggle).toBeDisabled();
    await expect(sidebar.getByRole('link', { name: '首页' })).toBeVisible();
  } else {
    await expect(page.locator('.app-shell')).not.toHaveClass(/sidebar-collapsed/);
    const before = (await page.locator('.workspace').boundingBox())!.width;
    await toggle.click();
    await expect(page.locator('.app-shell')).toHaveClass(/sidebar-collapsed/);
    await expect(sidebar.getByText('作品库', { exact: true })).toHaveCount(0);
    await expect
      .poll(async () => (await page.locator('.workspace').boundingBox())!.width)
      .toBeGreaterThan(before + 100);
    await detailFits(page);
    await page.getByRole('button', { name: '展开侧栏' }).click();
    await expect(page.locator('.app-shell')).not.toHaveClass(/sidebar-collapsed/);
  }
  await page.getByTestId('back-to-library').click();
  await expect(page).toHaveURL(/\/library$/);
  await expect(sidebar.getByRole('link', { name: '作品库' })).toHaveAttribute(
    'aria-current',
    'page',
  );
  await sidebar.getByRole('link', { name: '首页' }).click();
  await expect(page.getByTestId('featured')).toBeVisible();
  await expect(sidebar.getByRole('link', { name: '首页' })).toHaveAttribute('aria-current', 'page');
  await page.goBack();
  await expect(cards(page).first()).toBeVisible();
  await page.goBack();
  await expect(page.getByTestId('detail-title')).toBeVisible();
  await page.goForward();
  await page.goForward();
  await expect(page.getByTestId('featured')).toBeVisible();
  await page.reload();
  await expect(page.getByTestId('featured')).toBeVisible();
  // Disabled sidebar entries say why instead of pretending to work.
  for (const label of ['游玩计划', '发现', '私人空间'])
    await expect(sidebar.getByRole('button', { name: `${label} · 稍后开放` })).toBeDisabled();
  await recordLayout(page, info, 'shell-navigation', [
    'direct detail back link',
    info.project.name === 'narrow' ? 'auto-collapsed sidebar' : 'manual collapse/expand',
    'route highlight',
    'back/forward/reload',
  ]);
});

async function detailFits(page: Page) {
  await noHorizontalScroll(page);
  const title = await page.getByTestId('detail-title').boundingBox();
  expect(title!.x + title!.width).toBeLessThanOrEqual(page.viewportSize()!.width + 1);
}

test('Library sort, filter and view timing at 1500 works', async ({ page, browser }, info) => {
  test.skip(info.project.name !== '1080p', 'Sampled once at the reference viewport.');
  const runs = [];
  {
    const size = 1500;
    await page.goto('/library');
    await expect(cards(page).first()).toBeVisible();
    const settle = (condition: string) =>
      page.evaluate(async (condition) => {
        const check = new Function(`return (${condition});`) as () => boolean;
        const start = performance.now();
        await new Promise<void>((done) => {
          const poll = () => (check() ? done() : requestAnimationFrame(poll));
          poll();
        });
        await new Promise((done) => requestAnimationFrame(done));
        return performance.now() - start;
      }, condition);
    const firstId = () => page.locator('[data-game-card]').first().getAttribute('data-game-id');
    const idle = "!document.querySelector('.updating-label')";
    const sorts: number[] = [];
    const filters: number[] = [];
    const views: number[] = [];
    for (let round = 0; round < 10; round++) {
      for (const sort of ['playtime-desc', 'name-asc', 'curated']) {
        const before = await firstId();
        const timing = settle(
          `${idle} && document.querySelector('[data-game-card]')?.getAttribute('data-game-id') !== ${JSON.stringify(before)}`,
        );
        await page.getByRole('combobox', { name: '排序' }).selectOption(sort);
        sorts.push(await timing);
      }
      const kinds = page.getByRole('group', { name: '作品类型' });
      const audio = settle(
        `${idle} && [...document.querySelectorAll('.game-card-meta > span:first-child')].length > 0 && [...document.querySelectorAll('.game-card-meta > span:first-child')].every((node) => node.textContent === '音声 · DLsite')`,
      );
      await kinds.getByRole('button', { name: /音声/ }).click();
      filters.push(await audio);
      const all = settle(
        `${idle} && Number(document.querySelector('[data-testid="library-results"]').dataset.count) > ${size * 0.9}`,
      );
      await kinds.getByRole('button', { name: /全部/ }).click();
      filters.push(await all);
      const list = settle(`document.querySelectorAll('.view-list [data-game-card]').length > 0`);
      await page.getByRole('button', { name: '列表视图' }).click();
      views.push(await list);
      const grid = settle(`document.querySelectorAll('.view-grid [data-game-card]').length > 0`);
      await page.getByRole('button', { name: '网格视图' }).click();
      views.push(await grid);
    }
    expect(await cards(page).count()).toBeLessThan(200);
    expect(Number(await results(page).getAttribute('data-count'))).toBeGreaterThan(size * 0.9);
    const summary = (values: number[]) => {
      const sorted = [...values].sort((a, b) => a - b);
      return {
        median: sorted[Math.floor(sorted.length / 2)],
        p95: sorted[Math.ceil(sorted.length * 0.95) - 1],
        max: sorted.at(-1),
        samples: values,
      };
    };
    runs.push({
      size,
      sortToVisibleResultMs: summary(sorts),
      kindFilterToVisibleResultMs: summary(filters),
      viewToggleToVisibleResultMs: summary(views),
      mountedCardsAfterRuns: await cards(page).count(),
    });
    // Shared CI machines stall now and then: a single sample only has a hard limit locally.
    for (const values of [sorts, filters, views]) expect(summary(values).median).toBeLessThan(1000);
    if (!process.env.CI)
      for (const value of [...sorts, ...filters, ...views]) expect(value).toBeLessThan(1000);
  }
  await writeEvidence(info, 'library-interactions.json', {
    method:
      'Production build on the local service; 10 rounds (30 sorts, 20 kind filters, 20 view toggles). Timer starts in the page before the control changes (Playwright action latency included) and stops one animation frame after the expected result is in the DOM and no update is pending. No debounce involved.',
    browser: browser.version(),
    viewport: page.viewportSize(),
    runs,
  });
});

test('privacy holds across ranges, filters, edits and reloads', async ({ page }, info) => {
  test.skip(info.project.name !== '1080p', 'Logic check at the reference viewport.');
  for (const url of [
    '/',
    '/?scope=steam',
    '/?scope=dlsite-games',
    '/?scope=dlsite-media',
    '/?scope=games',
    '/library?view=list&sort=name-desc',
    '/library?kind=non-game',
    '/library?platform=dlsite&fav=1',
    '/library?q=PRIVATE',
    '/library?sort=playtime-desc',
  ]) {
    await page.goto(url);
    await expect(page.locator('main')).toBeVisible();
    await expect(page.locator('main [aria-busy="true"]')).toHaveCount(0);
    await noPrivateData(page);
  }
  // Editing an ordinary work and reloading never brings a private one back.
  await page.goto('/library/syn-00001');
  const status = page.getByRole('group', { name: '进度状态' });
  await expect(page.getByTestId('detail-status')).not.toHaveText('');
  const current = await page.getByTestId('detail-status').innerText();
  await status.getByText(current === '搁置' ? '进行中' : '搁置').click();
  await expect(status.getByText('已保存')).toBeVisible();
  await page.reload();
  await page.goto('/');
  await noPrivateData(page);
  // Private, hidden, quarantined and absent IDs are indistinguishable.
  const texts = [];
  for (const id of ['syn-private', 'syn-hidden', 'syn-quarantined', 'syn-99999']) {
    await page.goto(`/library/${id}`);
    await expect(page.getByTestId('game-unavailable')).toBeVisible();
    texts.push(await page.locator('main').innerText());
  }
  expect(new Set(texts).size).toBe(1);
  await screenshot(page, info, 'privacy-unavailable');
});
