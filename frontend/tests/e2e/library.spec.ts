import { expect, test, type Page } from '@playwright/test';
import { recordLayout, screenshot, writeEvidence, noHorizontalScroll } from './evidence';

const cards = (page: Page) => page.locator('[data-game-card]');
const scroll = (page: Page) => page.locator('[data-library-scroll]');

async function ready(page: Page, url = '/library') {
  await page.goto(url);
  await expect(cards(page).first()).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
}

async function noOverflow(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);
  const bounds = await cards(page).evaluateAll((elements) =>
    elements.map((element) => {
      const r = element.getBoundingClientRect();
      return { x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width, height: r.height };
    }),
  );
  for (const bound of bounds) {
    expect(bound.x).toBeGreaterThanOrEqual(0);
    expect(bound.right).toBeLessThanOrEqual((page.viewportSize()?.width ?? 0) + 1);
  }
  if (bounds.length) {
    const heights = bounds.map((bound) => bound.height);
    expect(Math.max(...heights) - Math.min(...heights)).toBeLessThan(1);
  }
  for (let i = 0; i < bounds.length; i++) {
    for (let j = i + 1; j < bounds.length; j++) {
      const left = bounds[i]!;
      const right = bounds[j]!;
      const overlapX = Math.min(left.right, right.right) - Math.max(left.x, right.x);
      const overlapY = Math.min(left.bottom, right.bottom) - Math.max(left.y, right.y);
      expect(overlapX > 1 && overlapY > 1).toBe(false);
    }
  }
}

test('grid, missing covers and long titles across viewport/DPR matrix', async ({ page }, info) => {
  const external: string[] = [];
  page.on('request', (request) => {
    if (/^https?:/.test(request.url()) && !request.url().startsWith('http://127.0.0.1:4173/'))
      external.push(request.url());
  });
  await ready(page);
  await expect(page.getByText('DEMO · 演示模式', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '我的作品库' })).toBeVisible();
  const columns = Number(await scroll(page).getAttribute('data-columns'));
  const expectedColumns: Record<string, [number, number]> = {
    '1080p': [7, 8],
    '2k': [9, 11],
    '4k': [14, 16],
    '4k-150': [9, 11],
    '4k-200': [7, 8],
    narrow: [4, 6],
    laptop: [4, 6],
  };
  const [min, max] = expectedColumns[info.project.name] ?? [1, 20];
  expect(columns).toBeGreaterThanOrEqual(min);
  expect(columns).toBeLessThanOrEqual(max);
  expect(await cards(page).count()).toBeLessThan(200);
  const sizes = await page.locator('.view-grid [data-cover]').evaluateAll((elements) =>
    elements.map((element) => {
      const r = element.getBoundingClientRect();
      return { width: r.width, height: r.height };
    }),
  );
  for (const size of sizes) {
    expect(size.width).toBeGreaterThanOrEqual(176);
    expect(size.width).toBeLessThanOrEqual(240.1);
    expect(Math.abs(size.height / size.width - 1.5)).toBeLessThan(0.01);
  }
  await noOverflow(page);
  await expect(page.locator('body')).not.toContainText('PRIVATE_SENTINEL');
  expect(await page.locator('body').ariaSnapshot()).not.toContain('PRIVATE_SENTINEL');
  await screenshot(page, info, 'library-grid');

  await page.getByRole('textbox', { name: '搜索作品' }).fill('晨雾回廊');
  await expect(cards(page).first()).toContainText('晨雾回廊');
  await expect(page.locator('[data-cover-kind="missing"]').first()).toBeVisible();
  await noOverflow(page);
  await screenshot(page, info, 'library-missing-cover');

  await page.getByRole('textbox', { name: '搜索作品' }).fill('跨越星海');
  await expect(cards(page)).toHaveCount(1);
  const title = page.locator('.game-title');
  await expect(title).toContainText('A Journey Beyond');
  const clamp = await title.evaluate((node) => ({
    lines: getComputedStyle(node).webkitLineClamp,
    height: node.getBoundingClientRect().height,
    line: Number.parseFloat(getComputedStyle(node).lineHeight),
  }));
  expect(clamp.lines).toBe('2');
  expect(clamp.height).toBeLessThanOrEqual(clamp.line * 2 + 1);
  await noOverflow(page);
  await screenshot(page, info, 'library-long-title');
  await recordLayout(page, info, 'library-grid', [
    'no horizontal scroll',
    `measured columns ${columns} within [${min}, ${max}]`,
    'card covers 176–240px wide, 2:3',
    'equal card heights, no overlap',
    'missing cover placeholder visible',
    'long title clamped to 2 lines',
  ]);
  expect(external).toEqual([]);
});

test('list view, real filters, empty results and privacy', async ({ page }, info) => {
  await ready(page, '/library?view=list');
  await expect(page.getByRole('list', { name: '作品列表' })).toBeVisible();
  await noOverflow(page);
  await screenshot(page, info, 'library-list');
  await recordLayout(page, info, 'library-list', ['no horizontal scroll', 'rows inside viewport']);
  await page.getByRole('combobox', { name: '类型' }).selectOption('探索');
  await page.getByRole('combobox', { name: '本机状态' }).selectOption('installed');
  await expect(page.locator('.list-genre').first()).toHaveText('探索');
  for (const genre of await page.locator('.list-genre').allTextContents())
    expect(genre).toBe('探索');
  for (const installed of await page.locator('.list-install').allTextContents())
    expect(installed).toContain('已安装');
  await page.getByRole('combobox', { name: '游玩状态' }).selectOption('playing');
  await expect(page.locator('.list-status').first()).toContainText('进行中');
  await page.getByRole('combobox', { name: '排序' }).selectOption('playtime-desc');
  await page.getByRole('textbox', { name: '搜索作品' }).fill('a-no-result-collection');
  await expect(page.getByText('还没有找到这段冒险')).toBeVisible();
  await noOverflow(page);
  await screenshot(page, info, 'library-no-results');
  await page.getByRole('textbox', { name: '搜索作品' }).fill('PRIVATE_SENTINEL');
  await expect(page.getByText('还没有找到这段冒险')).toBeVisible();
  expect(await page.locator('body').ariaSnapshot()).not.toContain('PRIVATE_SENTINEL_PRIVATE_');
  await page.getByRole('button', { name: '清除筛选', exact: true }).last().click();
  await expect(cards(page).first()).toBeVisible();
  await page.keyboard.press('Control+k');
  await expect(page.getByRole('textbox', { name: '搜索作品' })).toBeFocused();
});

test('feedback states recover and dialog returns focus', async ({ page }, info) => {
  await page.goto('/library?state=loading');
  await expect(page.getByRole('status', { name: '正在读取本地作品库' })).toBeVisible();
  await noOverflow(page);
  await screenshot(page, info, 'library-loading');
  await page.goto('/library?state=error');
  await expect(page.getByRole('alert')).toContainText('暂时未能读取作品库');
  await screenshot(page, info, 'library-error');
  await page.getByRole('button', { name: '重新加载' }).click();
  await expect(cards(page).first()).toBeVisible();
  const about = page.getByRole('button', { name: '关于演示', exact: true });
  await about.click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await expect(about).toBeFocused();
  await page.goto('/library?state=empty');
  await expect(page.getByText('收藏的故事，从这里开始')).toBeVisible();
  await noOverflow(page);
  await screenshot(page, info, 'library-empty');
  await page.getByRole('button', { name: '浏览演示收藏' }).click();
  await expect(cards(page).first()).toBeVisible();
});

test('favorites and container resize preserve the visible collection anchor', async ({
  page,
}, info) => {
  test.skip(info.project.name !== '1080p', 'Resize sequence is checked once.');
  await ready(page);
  const favorite = cards(page).first().getByRole('button');
  const before = await favorite.getAttribute('aria-pressed');
  await favorite.click();
  await expect(favorite).toHaveAttribute('aria-pressed', before === 'true' ? 'false' : 'true');
  const focusedGame = page.locator('[data-game-id="demo-00007"] .game-link');
  await focusedGame.focus();
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(scroll(page)).toHaveAttribute('data-columns', '5');
  await expect(focusedGame).toBeFocused();
  await page.getByRole('textbox', { name: '搜索作品' }).focus();
  await page.setViewportSize({ width: 1920, height: 1080 });
  await expect(page.getByRole('textbox', { name: '搜索作品' })).toBeFocused();
  await page.setViewportSize({ width: 1440, height: 900 });
  await scroll(page).evaluate((element) => {
    element.scrollTop = 3600;
  });
  const visibleAnchor = () =>
    scroll(page).evaluate((element) => {
      const box = element.getBoundingClientRect();
      const first = [...element.querySelectorAll('[data-game-card]')].find((card) => {
        const rect = card.getBoundingClientRect();
        return rect.bottom > box.top && rect.top < box.bottom;
      });
      return Number(first?.getAttribute('data-game-id')?.replace('demo-', ''));
    });
  await expect.poll(visibleAnchor).toBeGreaterThan(25);
  // Scrolling down hid the top bar; Ctrl+K brings its controls back where the list is.
  await page.keyboard.press('Control+k');
  const toggle = page.getByRole('button', { name: '收起侧栏', exact: true });
  await expect(toggle).toBeVisible();
  const anchor = await visibleAnchor();
  await toggle.click();
  await expect(scroll(page)).toHaveAttribute('data-columns', '6');
  expect(Math.abs((await visibleAnchor()) - anchor)).toBeLessThanOrEqual(6);
  await page.setViewportSize({ width: 2560, height: 1440 });
  await expect
    .poll(async () => Number(await scroll(page).getAttribute('data-columns')))
    .toBeGreaterThan(8);
  expect(Math.abs((await visibleAnchor()) - anchor)).toBeLessThanOrEqual(12);
  await noOverflow(page);
});

test('1500/5000 virtualization and measured browser performance', async ({
  page,
  browser,
}, info) => {
  test.skip(
    info.project.name !== '1080p',
    'Performance is sampled once at the reference viewport.',
  );
  const measurements = [];
  for (const size of [1500, 5000]) {
    const coverRequests = new Set<string>();
    page.on('request', (request) => {
      if (request.url().includes('/demo/covers/')) coverRequests.add(request.url());
    });
    await page.addInitScript(() => {
      const entries: number[] = [];
      Object.assign(window, { atlasLongTasks: entries });
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) entries.push(entry.duration);
      }).observe({ type: 'longtask', buffered: true });
    });
    await ready(page, `/library?size=${size}`);
    const firstReady = await page.evaluate(() => performance.now());
    const initialCards = await cards(page).count();
    const initialRequests = coverRequests.size;
    expect(initialCards).toBeLessThan(100);
    expect(initialRequests).toBeLessThanOrEqual(24);
    const latencies = [];
    const browserLatencies: number[] = [];
    for (let index = 0; index < 20; index++) {
      const expectedTitle = index % 2 ? '跨越星海' : '星穹观测站';
      await page.evaluate((expectedTitle) => {
        const input = document.querySelector<HTMLInputElement>('input[aria-label="搜索作品"]')!;
        const target = window as unknown as { atlasSearchTiming: Promise<number> };
        target.atlasSearchTiming = new Promise<number>((resolveTiming) => {
          input.addEventListener(
            'input',
            () => {
              const start = performance.now();
              const observer = new MutationObserver(() => {
                const cards = document.querySelectorAll('[data-game-card]');
                if (cards.length === 1 && cards[0]?.textContent?.includes(expectedTitle)) {
                  observer.disconnect();
                  requestAnimationFrame(() => resolveTiming(performance.now() - start));
                }
              });
              observer.observe(document.querySelector('main')!, {
                childList: true,
                subtree: true,
                characterData: true,
              });
            },
            { once: true },
          );
        });
      }, expectedTitle);
      const start = performance.now();
      await page.getByRole('textbox', { name: '搜索作品' }).fill(expectedTitle);
      await expect(cards(page)).toHaveCount(1);
      await expect(cards(page).first()).toContainText(index % 2 ? '跨越星海' : '星穹观测站');
      latencies.push(performance.now() - start);
      browserLatencies.push(
        await page.evaluate(
          () => (window as unknown as { atlasSearchTiming: Promise<number> }).atlasSearchTiming,
        ),
      );
    }
    await page.getByRole('textbox', { name: '搜索作品' }).fill('');
    await expect(cards(page)).not.toHaveCount(1);
    await page.getByRole('combobox', { name: '本机状态' }).selectOption('installed');
    await expect
      .poll(async () =>
        Number(await page.getByTestId('library-results').getAttribute('data-count')),
      )
      .toBeLessThan(size / 2);
    await expect(cards(page).first().locator('.installed-badge')).toBeVisible();
    await page.getByRole('combobox', { name: '本机状态' }).selectOption('all');
    await expect
      .poll(async () =>
        Number(await page.getByTestId('library-results').getAttribute('data-count')),
      )
      .toBeGreaterThan(size * 0.9);
    const scrolling = await scroll(page).evaluate(async (element) => {
      const started = performance.now();
      let frames = 0;
      await new Promise<void>((resolveFrame) => {
        const tick = () => {
          frames++;
          element.scrollTop += 18;
          if (performance.now() - started < 10_000) requestAnimationFrame(tick);
          else resolveFrame();
        };
        requestAnimationFrame(tick);
      });
      return { fps: (frames * 1000) / (performance.now() - started), scrollTop: element.scrollTop };
    });
    expect(scrolling.scrollTop).toBeGreaterThan(1000);
    expect(await cards(page).count()).toBeLessThan(100);
    latencies.sort((a, b) => a - b);
    browserLatencies.sort((a, b) => a - b);
    const longTasks = await page.evaluate(
      () => (window as unknown as { atlasLongTasks: number[] }).atlasLongTasks,
    );
    measurements.push({
      size,
      navigationToReadyMs: firstReady,
      searchEndToEndP95Ms: latencies[18],
      inputToVisibleResultP95Ms: browserLatencies[18],
      inputToVisibleSamples: browserLatencies,
      searchSamples: latencies,
      scrollFps: scrolling.fps,
      initialMountedCards: initialCards,
      finalMountedCards: await cards(page).count(),
      initialCoverRequests: initialRequests,
      longTasks,
      browser: browser.version(),
      viewport: page.viewportSize(),
    });
  }
  await writeEvidence(info, 'library.json', measurements);
});

test('scrolling down gives the list the window until the top of the list', async ({
  page,
}, info) => {
  test.skip(!['1080p', 'narrow'].includes(info.project.name), 'Behavior, not layout tiers.');
  await page.goto('/library');
  const list = scroll(page);
  const header = page.getByTestId('library-header');
  const search = page.getByLabel('搜索作品');
  const topbar = page.locator('.topbar');
  await expect(page.locator('[data-game-card]').first()).toBeVisible();
  await expect(search).toBeVisible();
  const before = await list.boundingBox();

  await list.hover();
  await page.mouse.wheel(0, 900);
  await expect(header).toBeHidden();
  await expect(topbar).toBeHidden();
  await expect(search).toBeHidden();
  const collapsed = await list.boundingBox();
  // The list really gets the room, and the scroll position it was at is kept.
  expect(collapsed!.height).toBeGreaterThan(before!.height + 200);
  expect(await list.evaluate((node) => node.scrollTop)).toBeGreaterThan(500);
  await noHorizontalScroll(page);
  await screenshot(page, info, 'library-scrolled');

  // Scrolling back up part of the way keeps the whole window for the works.
  await page.waitForTimeout(350);
  const deep = await list.evaluate((node) => node.scrollTop);
  await page.mouse.wheel(0, -120);
  await expect.poll(() => list.evaluate((node) => node.scrollTop)).toBeLessThan(deep);
  await page.waitForTimeout(350);
  await expect(header).toBeHidden();
  await expect(topbar).toBeHidden();

  // Ctrl+K works from the hidden state and lands in the search field.
  await page.keyboard.press('Control+k');
  await expect(search).toBeFocused();
  await expect(header).toBeVisible();

  await page.waitForTimeout(350);
  await list.hover();
  await page.mouse.wheel(0, 600);
  await expect(header).toBeHidden();
  await page.getByTestId('scroll-to-top').click();
  await expect.poll(() => list.evaluate((node) => node.scrollTop)).toBe(0);
  await expect(header).toBeVisible();
  await expect(page.getByTestId('scroll-to-top')).toHaveCount(0);

  // Scrolling all the way up by hand brings the controls back too.
  await page.waitForTimeout(350);
  await list.hover();
  await page.mouse.wheel(0, 600);
  await expect(header).toBeHidden();
  await page.waitForTimeout(350);
  await page.mouse.wheel(0, -5000);
  await expect(header).toBeVisible();
  await expect(topbar).toBeVisible();
});

test('a narrower result brings the header back even if the list cannot scroll', async ({
  page,
}) => {
  await page.goto('/library?view=grid');
  const scroller = page.getByTestId('library-scroll');
  await scroller.hover();
  await page.mouse.wheel(0, 800);
  await expect(page.locator('.library-page')).toHaveAttribute('data-collapsed', 'true');
  // Not Ctrl+K, which opens the header by itself: results narrow while it is tucked away.
  await page.evaluate(() => {
    const input = document.querySelector<HTMLInputElement>('input[aria-label="搜索作品"]')!;
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(
      input,
      '没有这样的作品-zzz',
    );
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await expect(page.getByTestId('library-results')).toHaveAttribute('data-count', '0');
  await expect(page.locator('.library-page')).toHaveAttribute('data-collapsed', 'false');
  await page.getByLabel('搜索作品').fill('');
  await expect(page.locator('.library-page')).toHaveAttribute('data-collapsed', 'false');
});

test('back to top answers a real press anywhere on it', async ({ page }) => {
  await page.goto('/library?view=grid');
  const scroller = page.getByTestId('library-scroll');
  for (const across of [0.1, 0.5, 0.9]) {
    // Just after opening, the header holds still for a moment on purpose.
    await page.waitForTimeout(350);
    await scroller.hover();
    await page.mouse.wheel(0, 900);
    const button = page.getByTestId('scroll-to-top');
    await expect(button).toBeVisible();
    const box = (await button.boundingBox())!;
    // A real mouse, held a moment: a press that moves the button loses the click.
    await page.mouse.move(box.x + box.width * across, box.y + box.height / 2);
    await page.mouse.down();
    await page.waitForTimeout(150);
    await page.mouse.up();
    await expect(page.locator('.library-page')).toHaveAttribute('data-collapsed', 'false');
    await expect.poll(() => scroller.evaluate((node) => node.scrollTop)).toBeLessThan(9);
  }
});

test('a short list keeps its controls in place', async ({ page }, info) => {
  test.skip(info.project.name !== '1080p', 'Behavior, not layout tiers.');
  await page.goto('/library?q=%E6%98%9F%E7%A9%B9');
  await expect(page.locator('[data-game-card]').first()).toBeVisible();
  const list = scroll(page);
  await list.hover();
  await page.mouse.wheel(0, 300);
  await page.waitForTimeout(350);
  await expect(page.getByTestId('library-header')).toBeVisible();
});

test('list columns show the facts and sort when clicked', async ({ page }, info) => {
  await page.goto('/library?view=list');
  await expect(page.getByRole('list', { name: '作品列表' })).toBeVisible();
  await noHorizontalScroll(page);
  if (['1080p', 'narrow', '4k'].includes(info.project.name))
    await screenshot(page, info, 'library-list-columns');
  if (info.project.name !== '1080p') return;

  const heading = page.getByRole('group', { name: '按栏目排序' });
  const firstMaker = () => page.locator('.list-maker').first().innerText();
  const sortSelect = page.getByRole('combobox', { name: '排序' });
  const maker = heading.getByRole('button', { name: /按制作方排序/ });

  await maker.click();
  await expect(sortSelect).toHaveValue('maker-asc');
  await expect(page).toHaveURL(/sort=maker-asc/);
  await expect(maker).toHaveAttribute('aria-pressed', 'true');
  const ascending = await firstMaker();
  await maker.click();
  await expect(sortSelect).toHaveValue('maker-desc');
  await expect.poll(firstMaker).not.toBe(ascending);

  // Each date column starts with the newest, and a dated row outranks an unknown one.
  const release = heading.getByRole('button', { name: /按发售日排序/ });
  await release.click();
  await expect(sortSelect).toHaveValue('release-desc');
  const dates = await page.locator('.list-release').allTextContents();
  expect(dates[0]).toMatch(/^\d{4}\/\d{2}\/\d{2}$/);
  expect([...dates].sort().reverse()).toEqual(dates);

  await heading.getByRole('button', { name: /按我的评价排序/ }).click();
  await expect(sortSelect).toHaveValue('rating-desc');
  await expect(page.locator('.list-rating').first()).toHaveAttribute('aria-label', '5 星');

  // A refresh keeps the choice.
  await page.reload();
  await expect(page.getByRole('combobox', { name: '排序' })).toHaveValue('rating-desc');
  await expect(
    page.getByRole('group', { name: '按栏目排序' }).getByRole('button', { name: /按我的评价排序/ }),
  ).toHaveAttribute('aria-pressed', 'true');
});
