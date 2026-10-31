import { expect, test, type Page } from '@playwright/test';
import { recordLayout, screenshot, writeEvidence } from './evidence';

const dashboard = (page: Page) => page.getByTestId('dashboard');

async function openDashboard(page: Page, query = '') {
  await page.goto(`/${query}`);
  await expect(dashboard(page)).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  await page.waitForFunction(() =>
    [...document.querySelectorAll<HTMLImageElement>('.dash-hero img')].every(
      (image) => image.complete,
    ),
  );
}

async function scrollMain(page: Page, top: number) {
  await page.locator('main').evaluate((element, y) => element.scrollTo({ top: y }), top);
  await page.waitForTimeout(150);
}

/** Width, module bounds and overlap checks shared by every viewport. */
async function layoutChecks(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);
  const width = page.viewportSize()!.width;
  const boxes = await page
    .locator('.dash-stat, .dash-module, .dash-tonight, .dash-recent, .dash-feature, .scope-switch')
    .evaluateAll((elements) =>
      elements.map((element) => {
        const r = element.getBoundingClientRect();
        return { x: r.x, right: r.right, width: r.width };
      }),
    );
  for (const box of boxes) {
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.right).toBeLessThanOrEqual(width + 1);
  }
  const title = page.locator('.dash-feature-title');
  if (await title.count()) {
    const [heading, actions] = await Promise.all([
      title.boundingBox(),
      page.locator('.dash-feature .hero-actions').boundingBox(),
    ]);
    expect(heading!.y + heading!.height).toBeLessThanOrEqual(actions!.y + 1);
  }
  const cover = await page.locator('.dash-feature [data-cover]').boundingBox();
  if (cover) expect(Math.abs(cover.height / cover.width - 1.5)).toBeLessThan(0.01);
  // Charts must not draw outside their module.
  for (const chart of await page.locator('.chart-box').all()) {
    const [inner, outer] = await Promise.all([
      chart.locator('svg').first().boundingBox(),
      chart.boundingBox(),
    ]);
    if (inner && outer)
      expect(inner.x + inner.width).toBeLessThanOrEqual(outer.x + outer.width + 1);
  }
  // Horizontal axis ticks never run into each other.
  const ticks = await page
    .locator('[data-chart="playtime"] .recharts-xAxis .recharts-cartesian-axis-tick text')
    .evaluateAll((nodes) =>
      nodes.map((node) => {
        const r = node.getBoundingClientRect();
        return { x: r.x, right: r.right };
      }),
    );
  for (let index = 1; index < ticks.length; index++)
    expect(ticks[index]!.x).toBeGreaterThanOrEqual(ticks[index - 1]!.right + 2);
}

test('dashboard across the viewport/DPR matrix', async ({ page }, info) => {
  const external: string[] = [];
  page.on('request', (request) => {
    if (/^https?:/.test(request.url()) && !request.url().startsWith('http://127.0.0.1:4173/'))
      external.push(request.url());
  });
  await openDashboard(page);
  await expect(page.getByText('DEMO · 演示模式', { exact: true })).toBeVisible();
  await expect(dashboard(page).locator('.demo-chip')).toBeVisible();
  await expect(page.getByRole('link', { name: '首页' })).toHaveAttribute('aria-current', 'page');
  const viewport = page.viewportSize()!;
  // Featured work and at least four key statistics share the first screen.
  const featured = await page.getByTestId('featured').boundingBox();
  expect(featured!.y + featured!.height).toBeLessThanOrEqual(viewport.height);
  const stats = page.locator('.dash-stat');
  await expect(stats).toHaveCount(4);
  if (info.project.name !== 'narrow')
    for (const stat of await stats.all()) {
      const box = await stat.boundingBox();
      expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
    }
  await layoutChecks(page);
  await expect(page.locator('body')).not.toContainText('PRIVATE_SENTINEL');
  expect(await page.locator('body').ariaSnapshot()).not.toContain('PRIVATE_SENTINEL');
  await screenshot(page, info, 'dashboard');
  await scrollMain(page, 99999);
  await expect(page.locator('[data-chart="playtime"] svg').first()).toBeVisible();
  await layoutChecks(page);
  // Wide layouts use more insight columns; type stays within its clamp instead of growing with vw.
  const insightColumns = await page
    .locator('.dash-insights')
    .evaluate((node) => getComputedStyle(node).gridTemplateColumns.split(' ').length);
  const mainWidth = (await page.locator('main').boundingBox())!.width;
  // No empty tracks: every column holds a module, so the grid spans its full width.
  expect(insightColumns).toBeLessThanOrEqual(await page.locator('.dash-insights > *').count());
  if (mainWidth >= 2400) expect(insightColumns).toBe(6);
  else expect(insightColumns).toBeGreaterThanOrEqual(mainWidth >= 1500 ? 4 : 2);
  const titleSize = await page
    .locator('.dash-feature-title')
    .evaluate((node) => Number.parseFloat(getComputedStyle(node).fontSize));
  expect(titleSize).toBeLessThanOrEqual(52);
  await recordLayout(page, info, 'dashboard', [
    'no horizontal scroll',
    'modules inside viewport',
    'feature title above actions; cover 2:3',
    'charts inside modules',
    `featured + 4 stats in first screen${info.project.name === 'narrow' ? ' (featured only at 720p)' : ''}`,
    `insight columns ${insightColumns} at main width ${Math.round(mainWidth)}`,
    `feature title ${titleSize}px (clamp max 52px)`,
  ]);
  await screenshot(page, info, 'dashboard-insights');
  expect(external).toEqual([]);
});

test('ranges switch real data and link to the matching Library', async ({ page }, info) => {
  test.skip(!['1080p', 'narrow', '4k-200'].includes(info.project.name), 'Representative ranges.');
  await openDashboard(page);
  const scopes = page.getByRole('group', { name: '首页范围' });
  const cases = [
    ['Steam 游戏', 'steam', true],
    ['DLsite 游戏', 'dlsite-games', true],
    ['DLsite 其他作品', 'dlsite-media', false],
    ['全部作品', 'all', true],
  ] as const;
  for (const [label, scope, hasGames] of cases) {
    await scopes.getByRole('button', { name: label }).click();
    await expect(dashboard(page)).toHaveAttribute('data-scope', scope);
    await expect(dashboard(page)).toHaveAttribute('data-ready', 'true');
    await expect(page).toHaveURL(scope === 'all' ? /\/$/ : new RegExp(`scope=${scope}`));
    await expect(page.locator('#playtime-title')).toHaveCount(hasGames ? 1 : 0);
    await expect(page.locator('#genre-title')).toHaveCount(hasGames ? 1 : 0);
    await expect(page.locator('#tonight-title')).toHaveText(
      hasGames ? '今晚玩什么' : '今晚看点、听点什么',
    );
    await page.waitForFunction(() =>
      [...document.querySelectorAll<HTMLImageElement>('.dash-hero img')].every(
        (image) => image.complete,
      ),
    );
    await layoutChecks(page);
    await screenshot(page, info, `dashboard-scope-${scope}`);
    if (scope === 'dlsite-games')
      await expect(page.getByTestId('stat-playtime')).toContainText('未提供');
  }
  // The headline count opens the same set in the Library.
  await scopes.getByRole('button', { name: 'DLsite 其他作品' }).click();
  await expect(dashboard(page)).toHaveAttribute('data-ready', 'true');
  const count = (await page.getByTestId('stat-works').locator('a').innerText()).replace(/\D/g, '');
  await page.getByTestId('stat-works').locator('a').click();
  await expect(page).toHaveURL(/\/library\?.*kind=non-game/);
  await expect(
    page.getByRole('group', { name: '作品类型' }).getByRole('button', { name: /非游戏/ }),
  ).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('library-results')).toHaveAttribute('data-count', count);
  await page.goBack();
  await expect(dashboard(page)).toHaveAttribute('data-scope', 'dlsite-media');
});

test('dashboard → detail → back, and recommendations stay put until asked', async ({
  page,
}, info) => {
  test.skip(!['1080p', 'narrow'].includes(info.project.name), 'Navigation smoke at 1080P/720P.');
  await openDashboard(page, '?scope=steam');
  const recs = page.getByTestId('recommendations');
  const first = await recs.innerText();
  await page.locator('.dash-insights').hover();
  expect(await recs.innerText()).toBe(first);
  await page.getByRole('button', { name: '换一批' }).click();
  await expect(recs).not.toHaveText(first);
  const card = page.getByTestId('recent-row').locator('a').first();
  const title = await card.locator('.recent-title').innerText();
  await card.click();
  await expect(page.getByTestId('detail-title')).toHaveText(title);
  await expect(page.getByTestId('back-to-library')).toHaveText('返回首页');
  await page.getByTestId('back-to-library').click();
  await expect(dashboard(page)).toHaveAttribute('data-scope', 'steam');
  await page.getByRole('link', { name: '作品库', exact: true }).click();
  await expect(page.locator('[data-game-card]').first()).toBeVisible();
  await page.getByRole('link', { name: '首页', exact: true }).click();
  await expect(dashboard(page)).toBeVisible();
});

test('demo source connections: expire, fail, retry, disconnect', async ({ page }, info) => {
  test.skip(
    !['1080p', 'narrow', '4k-200'].includes(info.project.name),
    'Panel states at 1080P, 720P and DPR 2.',
  );
  await openDashboard(page, '?state=source-expired');
  const dlsite = page.locator('.dash-sources [data-source="dlsite"]');
  await expect(dlsite).toContainText('会话已过期');
  await scrollMain(page, 99999);
  await screenshot(page, info, 'dashboard-source-expired');
  await page.getByRole('button', { name: '管理来源连接' }).click();
  const dialog = page.getByRole('dialog', { name: '来源连接' });
  await expect(dialog).toContainText('不会要求、接收或保存任何密码');
  await expect(dialog.locator('input')).toHaveCount(0);
  const row = dialog.locator('[data-source="dlsite"]');
  await row.getByRole('button', { name: '下次连接模拟失败' }).click();
  await row.getByRole('button', { name: '重新连接（演示）' }).click();
  await expect(row).toContainText('连接中');
  await expect(row).toContainText('连接失败');
  await screenshot(page, info, 'sources-error');
  await row.getByRole('button', { name: '重试（演示）' }).click();
  await expect(row).toContainText('已连接');
  const steam = dialog.locator('[data-source="steam"]');
  await steam.getByRole('button', { name: '断开（演示）' }).click();
  await expect(steam).toContainText('未连接');
  await expect(steam).toContainText('不会删除本地作品');
  await screenshot(page, info, 'sources-disconnected');
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole('button', { name: '管理来源连接' })).toBeFocused();
  await expect(page.locator('.dash-sources [data-source="steam"]')).toContainText('未连接');
  // Disconnecting keeps imported works.
  await page.goto('/library?platform=steam');
  await expect
    .poll(async () => Number(await page.getByTestId('library-results').getAttribute('data-count')))
    .toBeGreaterThan(900);
  await page.reload();
  await page.goto('/');
  await expect(page.locator('.dash-sources [data-source="steam"]')).toContainText('未连接');
});

test('demo download and extract: progress, failure, retry, cancel, reload', async ({
  page,
}, info) => {
  test.skip(
    !['1080p', 'narrow', '4k-200'].includes(info.project.name),
    'Task flow at 1080P, 720P and DPR 2.',
  );
  await page.clock.install();
  await page.goto('/library/demo-00033');
  await expect(page.getByTestId('detail-title')).toBeVisible();
  const action = page.getByTestId('download-action');
  await expect(action).toContainText('仅演示，不会下载或写入实际文件');
  await action.getByRole('button', { name: '演示下载并解压' }).click();
  await page.clock.runFor(250 * 6);
  await expect(action).toContainText(/下载中 \d+%/);
  await page.getByRole('button', { name: /下载任务/ }).click();
  const dialog = page.getByRole('dialog', { name: '下载与解压（演示）' });
  // The demo's time also runs by itself, so a slow machine may already be on the next step.
  await expect(dialog.locator('[data-task="demo-00033"] .is-current')).toHaveText(/下载|解压/);
  await screenshot(page, info, 'tasks-downloading');
  await page.keyboard.press('Escape');
  await page.clock.runFor(250 * 30);
  await expect(action).toContainText('已下载（演示）');
  await expect(page.locator('.hero-install')).toHaveText('已下载');

  // A fixed sample fails verification once, then succeeds on retry.
  await page.goto('/library/demo-00144');
  await expect(page.getByTestId('detail-title')).toBeVisible();
  await page.getByTestId('download-action').getByRole('button', { name: '演示下载并解压' }).click();
  await page.clock.runFor(250 * 20);
  await expect(page.getByTestId('download-action')).toContainText('校验失败');
  await page.getByRole('button', { name: /下载任务/ }).click();
  await expect(dialog.locator('[data-task="demo-00144"]')).toContainText('失败');
  await screenshot(page, info, 'tasks-failed');
  await dialog.locator('[data-task="demo-00144"]').getByRole('button', { name: '重试' }).click();
  await page.clock.runFor(250 * 30);
  await expect(dialog.locator('[data-task="demo-00144"]')).toContainText('已完成');
  await screenshot(page, info, 'tasks-done');
  await page.keyboard.press('Escape');

  // Single-file audio skips extraction; cancel stops it for good.
  await page.goto('/library/demo-00027');
  await page.getByTestId('download-action').getByRole('button', { name: '演示下载' }).click();
  await page.clock.runFor(250 * 3);
  await page.getByTestId('download-action').getByRole('button', { name: '取消' }).click();
  await page.clock.runFor(250 * 60);
  await expect(page.getByTestId('download-action')).toContainText('已取消');
  await expect(page.locator('.hero-install')).toHaveText('未下载');
  await page.getByRole('button', { name: /下载任务/ }).click();
  await expect(dialog.locator('[data-task="demo-00027"]')).toContainText('已取消');
  await expect(dialog.locator('[data-task="demo-00027"] .is-skipped')).toHaveText('无需解压');
  await screenshot(page, info, 'tasks-cancelled');
  await page.keyboard.press('Escape');

  // Steam and viewer-only works offer no download.
  await page.goto('/library/demo-00001');
  await expect(page.getByTestId('download-action')).toHaveCount(0);
  await page.goto('/library/demo-00048');
  await expect(page.getByTestId('download-action')).toContainText('仅限 DLsite 官方阅读器');

  // The completed result persists; an unfinished task does not survive a reload.
  await page.goto('/library/demo-00051');
  await page.getByTestId('download-action').getByRole('button', { name: '演示下载并解压' }).click();
  await page.clock.runFor(250 * 4);
  await page.reload();
  await expect(
    page.getByTestId('download-action').getByRole('button', { name: '演示下载并解压' }),
  ).toBeVisible();
  await page.goto('/library?platform=dlsite&kind=game&q=0033');
  await expect(page.locator('[data-game-id="demo-00033"]')).toContainText('已下载');
  await page.goto('/');
  await expect(page.getByTestId('queue-summary')).toContainText('下载队列为空');
});

test('dashboard feedback states', async ({ page }, info) => {
  test.skip(
    !['1080p', 'narrow', '4k-200'].includes(info.project.name),
    'Feedback states at 1080P, 720P and DPR 2.',
  );
  await page.goto('/?state=loading');
  await expect(page.getByRole('status', { name: '正在整理首页' })).toBeVisible();
  await screenshot(page, info, 'dashboard-loading');
  await page.goto('/?state=error');
  await expect(page.getByRole('alert')).toContainText('暂时未能整理首页');
  await screenshot(page, info, 'dashboard-error');
  await page.getByRole('button', { name: '重新加载' }).click();
  await expect(dashboard(page)).toBeVisible();
  await page.goto('/?state=empty');
  await expect(page.getByText('收藏的故事，从这里开始')).toBeVisible();
  await screenshot(page, info, 'dashboard-empty');
  await page.getByRole('button', { name: '浏览演示收藏' }).click();
  await expect(page.getByTestId('featured')).toBeVisible();
});

test('dashboard timing at 1500 and 5000 works', async ({ page, browser }, info) => {
  test.skip(info.project.name !== '1080p', 'Sampled once at the reference viewport.');
  const results = [];
  for (const size of [1500, 5000] as const) {
    const suffix = size === 5000 ? '?size=5000' : '';
    const loads: number[] = [];
    for (let index = 0; index < 5; index++) {
      await page.goto(`/library${suffix}`);
      await expect(page.locator('[data-game-card]').first()).toBeVisible();
      loads.push(
        await page.evaluate(async () => {
          const start = performance.now();
          document.querySelector<HTMLAnchorElement>('a[aria-label="首页"]')!.click();
          await new Promise<void>((done) => {
            const check = () =>
              document.querySelector('[data-testid="featured"]') &&
              document.querySelectorAll('.dash-stat').length === 4
                ? done()
                : requestAnimationFrame(check);
            check();
          });
          await new Promise((done) => requestAnimationFrame(done));
          return performance.now() - start;
        }),
      );
    }
    const switches: number[] = [];
    const order = ['steam', 'dlsite-media', 'games', 'dlsite-games', 'all'];
    const labels: Record<string, string> = {
      steam: 'Steam 游戏',
      'dlsite-media': 'DLsite 其他作品',
      games: '全部游戏',
      'dlsite-games': 'DLsite 游戏',
      all: '全部作品',
    };
    for (let index = 0; index < 10; index++) {
      const scope = order[index % order.length]!;
      switches.push(
        await page.evaluate(
          async ({ scope, label }) => {
            const button = [
              ...document.querySelectorAll<HTMLButtonElement>('.scope-switch button'),
            ].find((entry) => entry.textContent === label)!;
            const start = performance.now();
            button.click();
            await new Promise<void>((done) => {
              const check = () =>
                // The new range's own numbers, not the dimmed previous range.
                document.querySelector(`[data-scope="${scope}"][data-ready="true"]`)
                  ? done()
                  : requestAnimationFrame(check);
              check();
            });
            await new Promise((done) => requestAnimationFrame(done));
            return performance.now() - start;
          },
          { scope, label: labels[scope]! },
        ),
      );
    }
    const median = (values: number[]) =>
      [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)];
    results.push({
      size,
      navigateToFeaturedAndStatsMs: {
        median: median(loads),
        max: Math.max(...loads),
        samples: loads,
      },
      scopeSwitchMs: { median: median(switches), max: Math.max(...switches), samples: switches },
      browser: browser.version(),
      viewport: page.viewportSize(),
    });
    for (const value of [...loads, ...switches]) expect(value).toBeLessThan(1500);
  }
  await writeEvidence(info, 'dashboard.json', results);
});
