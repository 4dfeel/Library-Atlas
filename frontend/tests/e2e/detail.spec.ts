import { expect, test, type Page } from '@playwright/test';
import { noPrivateData, recordLayout, screenshot, writeEvidence } from './evidence';
import { clearPersonal } from './real-service';

const title = (page: Page) => page.getByTestId('detail-title');
const libraryScroll = (page: Page) => page.locator('[data-library-scroll]');
const searchBox = (page: Page) => page.getByRole('textbox', { name: '搜索作品' });

/** Named or fixed-seed samples of the isolated test library. */
const samples = {
  complete: 'syn-steam-1001',
  noAchievements: 'syn-00001',
  noRecord: 'syn-00000',
  unplayed: 'syn-00004',
  noCover: 'syn-00002',
  longTitle: 'syn-long-title',
  unbrokenTitle: 'syn-unbroken-title',
  privateId: 'syn-private',
  hiddenId: 'syn-hidden',
  absentId: 'syn-99999',
};

async function openDetail(page: Page, id: string, query = '') {
  await page.goto(`/library/${id}${query}`);
  await expect(title(page)).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  await page.waitForFunction(() =>
    [...document.querySelectorAll<HTMLImageElement>('.detail-hero img')].every(
      (image) => image.complete,
    ),
  );
}

type Box = { x: number; y: number; right: number; bottom: number; width: number; height: number };

async function box(page: Page, selector: string): Promise<Box> {
  return page
    .locator(selector)
    .first()
    .evaluate((element) => {
      const r = element.getBoundingClientRect();
      return { x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width, height: r.height };
    });
}

const overlaps = (a: Box, b: Box) =>
  Math.min(a.right, b.right) - Math.max(a.x, b.x) > 1 &&
  Math.min(a.bottom, b.bottom) - Math.max(a.y, b.y) > 1;

/** Page width, key element bounds, cover ratio and title/action separation. */
async function detailLayout(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);
  const width = page.viewportSize()!.width;
  const heading = await box(page, '[data-testid="detail-title"]');
  const cover = await box(page, '.hero-cover [data-cover]');
  const actions = await box(page, '.hero-actions');
  const back = await box(page, '[data-testid="back-to-library"]');
  for (const item of [heading, cover, actions, back]) {
    expect(item.x).toBeGreaterThanOrEqual(0);
    expect(item.right).toBeLessThanOrEqual(width + 1);
  }
  expect(Math.abs(cover.height / cover.width - 1.5)).toBeLessThan(0.01);
  expect(overlaps(heading, actions)).toBe(false);
  expect(overlaps(heading, cover)).toBe(false);
  expect(overlaps(back, heading)).toBe(false);
  // Long titles wrap instead of clipping: the heading's content fits its box.
  expect(await title(page).evaluate((node) => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
  const body = await page
    .locator('.about-text p, .section-empty')
    .first()
    .evaluate((node) => node.getBoundingClientRect().width);
  expect(body).toBeLessThanOrEqual(900);
}

test('complete detail across the viewport/DPR matrix', async ({ page }, info) => {
  const external: string[] = [];
  page.on('request', (request) => {
    if (/^https?:/.test(request.url()) && !request.url().startsWith('http://127.0.0.1:4173/'))
      external.push(request.url());
  });
  await openDetail(page, samples.complete);
  await expect(page.locator('.detail-hero .sample-chip')).toHaveText('测试数据 · 合成样本');
  await expect(page.getByText('测试库 · 合成数据', { exact: true })).toBeVisible();
  await expect(title(page)).toBeFocused();
  expect(await page.title()).toBe('同名样本：夜行灯塔 · Library Atlas');
  await detailLayout(page);
  await noPrivateData(page);
  await screenshot(page, info, 'detail-complete');
  await recordLayout(page, info, 'detail-complete', [
    'no horizontal scroll',
    'title/cover/actions/back inside viewport and not overlapping',
    'cover 2:3',
    'body measure <= 900px',
  ]);
  await page.locator('.detail-page').evaluate((element) => element.scrollTo({ top: 99999 }));
  await screenshot(page, info, 'detail-complete-body');
  expect(external).toEqual([]);
});

test('missing art and long mixed titles across the viewport/DPR matrix', async ({ page }, info) => {
  await openDetail(page, samples.noCover);
  await expect(page.locator('.detail-hero')).toHaveAttribute('aria-labelledby', 'detail-title');
  await expect(page.locator('.hero-cover [data-cover-kind="missing"]')).toBeVisible();
  await expect(page.locator('.hero-cover').getByRole('img', { name: '暂无封面' })).toBeVisible();
  await detailLayout(page);
  await screenshot(page, info, 'detail-no-cover');

  // Chinese, Japanese and English in one title; and one with no break opportunities.
  await openDetail(page, samples.longTitle);
  await expect(title(page)).toContainText('The Very Long Journey');
  await detailLayout(page);
  await screenshot(page, info, 'detail-long-title');
  await openDetail(page, samples.unbrokenTitle);
  await detailLayout(page);
  await screenshot(page, info, 'detail-long-title-unbroken');
  await recordLayout(page, info, 'detail-art-and-titles', [
    'no horizontal scroll',
    'title/cover/actions/back inside viewport and not overlapping',
    'cover 2:3',
    'title wraps without clipping',
    'body measure <= 900px',
  ]);
});

test('edge states render honest semantics without overflow', async ({ page }, info) => {
  test.skip(
    !['1080p', 'narrow', '4k-200'].includes(info.project.name),
    'Representative states: 1080P, 1280×720 and one high-DPR viewport.',
  );
  const facts = page.locator('.hero-facts');
  await page.goto('/library');
  await clearPersonal(page, samples.unplayed);
  await clearPersonal(page, samples.noRecord);
  await openDetail(page, samples.unplayed);
  await expect(facts).toContainText('尚未开始');
  await expect(facts).toContainText('暂无记录');
  await expect(page.getByTestId('detail-status')).toHaveText('未开始');
  await screenshot(page, info, 'detail-unplayed');

  await openDetail(page, samples.noAchievements);
  await expect(facts).toContainText('未提供');
  await expect(page.getByTestId('achievements')).toContainText('不以 0% 显示');
  await expect(page.getByRole('progressbar')).toHaveCount(0);
  await screenshot(page, info, 'detail-no-achievements');

  await openDetail(page, samples.noRecord);
  await expect(page.getByText('未评分')).toBeVisible();
  await expect(page.getByText(/还没有备注/)).toBeVisible();
  await page.getByRole('button', { name: '添加备注' }).click();
  await page.getByRole('textbox', { name: /个人备注/ }).fill('第二章的谜题需要纸笔记录。');
  await expect(page.getByText('有未保存的修改')).toBeVisible();
  await page
    .locator('.detail-side')
    .evaluate((element) => element.scrollIntoView({ block: 'center' }));
  await screenshot(page, info, 'detail-editing');
  await detailLayout(page);
});

test('loading, error, unavailable and private IDs', async ({ page }, info) => {
  test.skip(
    !['1080p', 'narrow', '4k-200'].includes(info.project.name),
    'Feedback states at 1080P, 720P and DPR 2.',
  );
  const address = `**/api/v1/works/${samples.complete}`;
  await page.route(address, () => undefined);
  await page.goto(`/library/${samples.complete}`);
  await expect(page.getByRole('status', { name: '正在读取作品详情' })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);
  await screenshot(page, info, 'detail-loading');

  await page.unroute(address);
  await page.route(address, (route) =>
    route.fulfill({ status: 500, json: { error: { code: 'x', message: '读取没有成功。' } } }),
  );
  await page.goto(`/library/${samples.complete}`);
  await expect(page.getByRole('heading', { name: '暂时未能读取资料' })).toBeVisible();
  await screenshot(page, info, 'detail-error');
  await page.unroute(address);
  await page.getByRole('button', { name: '重新加载' }).click();
  await expect(title(page)).toHaveText('同名样本：夜行灯塔');

  const texts: string[] = [];
  for (const id of [samples.privateId, samples.hiddenId, samples.absentId]) {
    await page.goto(`/library/${id}`);
    const unavailable = page.getByTestId('game-unavailable');
    await expect(unavailable).toBeVisible();
    await expect(unavailable.getByRole('heading', { name: '找不到这部作品' })).toBeFocused();
    await noPrivateData(page);
    await expect(page.locator('.detail-hero, [data-cover], textarea')).toHaveCount(0);
    texts.push(await page.locator('main').innerText());
  }
  expect(new Set(texts).size).toBe(1);
  await screenshot(page, info, 'detail-unavailable');
  await page.getByRole('button', { name: '返回作品库' }).click();
  await expect(page).toHaveURL(/\/library$/);
  await expect(page.locator('[data-game-card]').first()).toBeVisible();
});

test('a pending search never writes Library state onto another page URL', async ({
  page,
}, info) => {
  test.skip(info.project.name !== '1080p', 'Timing logic; one tier is enough.');
  await page.goto('/library');
  await expect(page.locator('[data-game-card]').first()).toBeVisible();
  // History moves on while the search debounce is still pending, before React unmounts.
  await searchBox(page).fill('灯塔');
  await page.evaluate(() => window.history.pushState({}, '', '/library/syn-00001'));
  await page.waitForTimeout(400);
  await expect(page).toHaveURL(/\/library\/syn-00001$/);
});

test('grid and list round trips restore Library state and history works', async ({
  page,
}, info) => {
  test.skip(!['1080p', 'narrow'].includes(info.project.name), 'Navigation smoke at 1080P/720P.');
  await page.goto('/library?genre=RPG&sort=name-asc');
  await expect(page.getByRole('combobox', { name: '类型' })).toHaveValue('RPG');
  await searchBox(page).fill('灯塔');
  await expect(page).toHaveURL(/q=%E7%81%AF%E5%A1%94/);
  const firstCard = page.locator('[data-game-card]').first();
  const openedId = await firstCard.getAttribute('data-game-id');
  const openedTitle = await firstCard.locator('.game-link').innerText();
  await firstCard.locator('.game-link').click();
  await expect(title(page)).toHaveText(openedTitle);
  await expect(page).toHaveURL(new RegExp(`/library/${openedId}$`));
  await page.getByTestId('back-to-library').click();
  await expect(searchBox(page)).toHaveValue('灯塔');
  await expect(page.getByRole('combobox', { name: '类型' })).toHaveValue('RPG');
  await expect(page.getByRole('combobox', { name: '排序' })).toHaveValue('name-asc');
  await expect(page.locator(`[data-game-id="${openedId}"] .game-link`)).toBeFocused();

  // List view, deep scroll, then browser Back/Forward and refresh.
  await page.goto('/library?view=list&sort=playtime-desc');
  const scroll = libraryScroll(page);
  await expect(page.getByRole('list', { name: '作品列表' })).toBeVisible();
  await scroll.evaluate((element) => {
    element.scrollTop = 4600;
  });
  await expect.poll(() => scroll.evaluate((element) => element.scrollTop)).toBeGreaterThan(4000);
  // Wait for the scroll to settle, then take the row across the middle of the view: one near the
  // edge of the virtual window can be recycled before the test gets to it.
  let settled = -1;
  await expect
    .poll(async () => {
      const now = await scroll.evaluate((element) => element.scrollTop);
      const same = now === settled;
      settled = now;
      return same;
    })
    .toBe(true);
  const before = settled;
  const rowId = await scroll.evaluate((element) => {
    const box = element.getBoundingClientRect();
    const middle = box.top + box.height / 2;
    const rows = [...element.querySelectorAll<HTMLElement>('[data-game-card]')];
    const hit = rows.find((item) => {
      const rect = item.getBoundingClientRect();
      return rect.top <= middle && rect.bottom >= middle && item.querySelector('.game-link');
    });
    return hit?.dataset.gameId ?? null;
  });
  // Pin by ID: the virtual list may re-render between locator resolutions.
  const pinned = page.locator(`[data-game-id="${rowId}"]`);
  const listedStatus = await pinned.locator('.list-status').innerText();
  await pinned.locator('.game-link').click();
  await expect(page.getByTestId('detail-status')).toHaveText(listedStatus);
  await page.reload();
  await expect(title(page)).toBeVisible();
  await page.goBack();
  await expect(page.getByRole('list', { name: '作品列表' })).toBeVisible();
  // Back deep in the list the controls are tucked away; the address still holds the sort.
  await expect(page).toHaveURL(/sort=playtime-desc/);
  await expect
    .poll(() => scroll.evaluate((element) => element.scrollTop))
    .toBeGreaterThan(before - 100);
  expect(Math.abs((await scroll.evaluate((element) => element.scrollTop)) - before)).toBeLessThan(
    100,
  );
  await page.goForward();
  await expect(page).toHaveURL(new RegExp(`/library/${rowId}$`));
  await expect(title(page)).toBeVisible();

  // A detail opened directly has no Library entry behind it; Back still works.
  const fresh = await page.context().newPage();
  await fresh.goto(`/library/${samples.longTitle}`);
  await expect(title(fresh)).toBeVisible();
  await fresh.getByTestId('back-to-library').click();
  await expect(fresh).toHaveURL(/\/library$/);
  await expect(fresh.locator('[data-game-card]').first()).toBeVisible();
  await fresh.close();
});

test('keyboard: Ctrl+K, note shortcuts, status and rating, reduced motion', async ({
  page,
}, info) => {
  test.skip(!['1080p', 'narrow'].includes(info.project.name), 'Keyboard smoke at 1080P/720P.');
  await page.goto('/library');
  await clearPersonal(page, samples.noRecord);
  await openDetail(page, samples.noRecord);
  expect(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches)).toBe(
    true,
  );
  await page.getByRole('button', { name: '添加备注' }).focus();
  await page.keyboard.press('Enter');
  const note = page.getByRole('textbox', { name: /个人备注/ });
  await expect(note).toBeFocused();
  await page.keyboard.type('键盘输入');
  await page.keyboard.press('Control+k');
  await expect(note).toBeFocused();
  await expect(page).toHaveURL(new RegExp(`/library/${samples.noRecord}$`));
  await page.keyboard.press('Escape');
  await expect(note).toBeVisible(); // Esc never discards a dirty draft.
  await page.keyboard.press('Control+Enter');
  await expect(page.getByText('已保存').first()).toBeVisible();
  await expect(page.getByRole('button', { name: '编辑备注' })).toBeFocused();

  const status = page.getByRole('group', { name: '进度状态' });
  await status.getByRole('radio', { name: '未开始' }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(status.getByRole('radio', { name: '进行中' })).toBeChecked();
  const rating = page.getByRole('group', { name: /个人评分/ });
  await rating.getByRole('radio', { name: '1 星' }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(rating.getByText('2 / 5')).toBeVisible();

  await page.locator('body').click({ position: { x: 5, y: 5 } });
  await page.keyboard.press('Control+k');
  await expect(searchBox(page)).toBeFocused();
  await expect(page).toHaveURL(/\/library$/);
});

test('edits reach the Library, survive a reload and fail visibly', async ({ page }, info) => {
  test.skip(!['1080p', 'narrow'].includes(info.project.name), 'Edit flow at 1080P/720P.');
  await page.goto('/library');
  await clearPersonal(page, samples.complete);
  await clearPersonal(page, samples.noRecord);
  await openDetail(page, samples.complete);
  const status = page.getByRole('group', { name: '进度状态' });
  await status.getByText('搁置').click();
  await expect(status.getByText('已保存')).toBeVisible();
  await expect(page.getByTestId('detail-status')).toHaveText('搁置');
  const favorite = page.locator('.hero-actions').getByRole('button', { name: /收藏/ });
  await expect(favorite).toHaveAttribute('aria-pressed', 'false');
  await favorite.click();
  await expect(favorite).toHaveAttribute('aria-pressed', 'true');
  const rating = page.getByRole('group', { name: /个人评分/ });
  await rating.getByRole('radio', { name: '3 星' }).click({ force: true });
  await expect(rating.getByText('3 / 5')).toBeVisible();
  await expect(rating.getByText('已保存')).toBeVisible();
  await expect(favorite).toBeEnabled();

  await page.reload();
  await expect(page.getByTestId('detail-status')).toHaveText('搁置');
  await expect(page.getByText('3 / 5')).toBeVisible();
  await page.getByTestId('back-to-library').click();
  await page.getByRole('combobox', { name: '游玩状态' }).selectOption('paused');
  await searchBox(page).fill('夜行灯塔');
  const card = page.locator(`[data-game-id="${samples.complete}"]`);
  await expect(card).toContainText('搁置');
  const toggle = card.getByRole('button', { name: /收藏 同名样本/ });
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-pressed', 'false');

  await openDetail(page, samples.noRecord);
  await page.route(`**/api/v1/works/${samples.noRecord}/personal`, (route) =>
    route.fulfill({ status: 500, json: { error: { code: 'x', message: '没有保存。' } } }),
  );
  await page.getByRole('button', { name: '添加备注' }).click();
  await page.getByRole('textbox', { name: /个人备注/ }).fill('这条不会保存');
  await page.getByRole('button', { name: '保存备注' }).click();
  await expect(page.locator('.note-field [role="alert"]')).toBeVisible();
  await expect(page.getByRole('textbox', { name: /个人备注/ })).toHaveValue('这条不会保存');
  await page
    .locator('.detail-side')
    .evaluate((element) => element.scrollIntoView({ block: 'center' }));
  await screenshot(page, info, 'detail-save-error');
});

test('Library and detail comparison captures', async ({ page }, info) => {
  test.skip(!['1080p', 'narrow', '4k'].includes(info.project.name), 'Comparison set.');
  await page.goto('/library');
  await expect(page.locator('[data-game-card]').first()).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  await screenshot(page, info, 'compare-library');
  await page.locator('[data-game-card] .game-link').nth(5).click();
  await expect(title(page)).toBeVisible();
  await page.waitForFunction(() =>
    [...document.querySelectorAll<HTMLImageElement>('.detail-hero img')].every(
      (image) => image.complete,
    ),
  );
  await screenshot(page, info, 'compare-detail');
});

test('detail open/return timing at 1500 records', async ({ page, browser }, info) => {
  test.skip(info.project.name !== '1080p', 'Sampled once at the reference viewport.');
  const results = [];
  {
    const size = 1500;
    await page.goto('/library');
    await expect(page.locator('[data-game-card]').first()).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    const openSamples: number[] = [];
    const backSamples: number[] = [];
    for (let index = 0; index < 10; index++) {
      const id = await page
        .locator('[data-game-card]')
        .nth(index % 6)
        .getAttribute('data-game-id');
      const open = await page.evaluate(async (gameId) => {
        const link = document.querySelector<HTMLAnchorElement>(
          `[data-game-id="${gameId}"] .game-link`,
        )!;
        const start = performance.now();
        link.click();
        await new Promise<void>((done) => {
          const check = () =>
            document.querySelector('[data-testid="detail-title"]')
              ? done()
              : requestAnimationFrame(check);
          check();
        });
        await new Promise((done) => requestAnimationFrame(done));
        return performance.now() - start;
      }, id);
      openSamples.push(open);
      await expect(title(page)).toBeVisible();
      const back = await page.evaluate(async () => {
        const start = performance.now();
        document.querySelector<HTMLAnchorElement>('[data-testid="back-to-library"]')!.click();
        await new Promise<void>((done) => {
          const check = () =>
            document.querySelector('[data-game-card]') ? done() : requestAnimationFrame(check);
          check();
        });
        await new Promise((done) => requestAnimationFrame(done));
        return performance.now() - start;
      });
      backSamples.push(back);
      await expect(page.locator('[data-game-card]').first()).toBeVisible();
    }
    const sorted = (values: number[]) => [...values].sort((a, b) => a - b);
    results.push({
      size,
      repetitions: 10,
      openToTitleMs: { median: sorted(openSamples)[5], max: Math.max(...openSamples) },
      backToFirstCardMs: { median: sorted(backSamples)[5], max: Math.max(...backSamples) },
      openSamples,
      backSamples,
      browser: browser.version(),
      viewport: page.viewportSize(),
    });
    // Shared CI machines stall now and then, so a single sample only has a hard limit
    // locally. The median budget applies everywhere and catches a real slowdown.
    const median = (values: number[]) =>
      [...values].sort((left, right) => left - right)[Math.floor(values.length / 2)]!;
    expect(median(openSamples)).toBeLessThan(1000);
    expect(median(backSamples)).toBeLessThan(1000);
    const sampleLimit = process.env.CI ? 5000 : 1000;
    for (const value of [...openSamples, ...backSamples]) expect(value).toBeLessThan(sampleLimit);
  }
  await writeEvidence(info, 'detail.json', results);
});

test('work-kind tabs, platform filter and a DLsite detail', async ({ page }, info) => {
  test.skip(!['1080p', 'narrow', '4k'].includes(info.project.name), 'Representative viewports.');
  await page.goto('/library');
  await expect(page.locator('[data-game-card]').first()).toBeVisible();
  const kinds = page.getByRole('group', { name: '作品类型' });
  await kinds.getByRole('button', { name: /音声/ }).click();
  await expect(page).toHaveURL(/kind=audio/);
  await expect(page.locator('[data-game-card]').first()).toContainText('音声 · DLsite');
  for (const meta of await page.locator('.game-card-meta > span:first-child').allTextContents())
    expect(meta).toBe('音声 · DLsite');
  await page.evaluate(() => document.fonts.ready);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);
  await screenshot(page, info, 'library-kind-audio');
  await kinds.getByRole('button', { name: /全部/ }).click();
  await page.getByRole('combobox', { name: '平台' }).selectOption('steam');
  await expect(page.locator('[data-game-card]').first()).toBeVisible();
  for (const meta of await page.locator('.game-card-meta > span:first-child').allTextContents())
    expect(meta).not.toContain('DLsite');

  await openDetail(page, 'syn-dlsite-1001');
  await expect(page.locator('.platform-chip')).toHaveText('DLsite');
  await expect(page.locator('.hero-facts')).toContainText('最近收听');
  await expect(page.locator('.hero-facts')).not.toContainText('累计游玩');
  await expect(page.getByRole('heading', { name: /成就进度/ })).toHaveCount(0);
  await detailLayout(page);
  await screenshot(page, info, 'detail-dlsite');
});

test('every source and work kind shows only the fields that apply', async ({ page }, info) => {
  test.skip(
    !['1080p', 'narrow', '4k-200'].includes(info.project.name),
    'Representative states: 1080P, 1280×720 and one high-DPR viewport.',
  );
  const cases = [
    { id: 'syn-steam-1001', name: 'steam-game', kind: '游戏', usage: '最近游玩' },
    { id: 'syn-multipart', name: 'dlsite-game', kind: '游戏', usage: '最近游玩' },
    { id: 'syn-00005', name: 'dlsite-image', kind: '漫画/图像', usage: '最近阅读' },
    { id: 'syn-00017', name: 'dlsite-audio', kind: '音声', usage: '最近收听' },
    { id: 'syn-00011', name: 'dlsite-video', kind: '视频', usage: '最近观看' },
    { id: 'syn-00023', name: 'dlsite-other', kind: '其他', usage: '最近打开' },
  ];
  for (const sample of cases) {
    await openDetail(page, sample.id);
    const steam = sample.name.startsWith('steam');
    const game = sample.name.endsWith('game');
    await expect(page.locator('.platform-chip')).toHaveText(steam ? 'Steam' : 'DLsite');
    await expect(page.locator('.hero-eyebrow')).toContainText(`${sample.kind} · `);
    await expect(page.locator('.hero-facts')).toContainText(sample.usage);
    // Play time belongs to games; nothing else is filled with fake values.
    await expect(page.locator('.hero-facts')).toContainText(game ? '累计游玩' : '作品类型');
    if (!game) await expect(page.locator('.hero-facts')).not.toContainText('累计游玩');
    await expect(page.getByTestId('achievements')).toHaveCount(steam ? 1 : 0);
    await expect(page.getByTestId('download-action')).toHaveCount(steam ? 0 : 1);
    if (sample.id === 'syn-00005')
      await expect(page.getByTestId('download-action')).toContainText('仅限 DLsite 官方阅读器');
    await detailLayout(page);
    await noPrivateData(page);
    await screenshot(page, info, `detail-kind-${sample.name}`);
  }
  await recordLayout(page, info, 'detail-kinds', [
    'Steam/DLsite × game/image/audio/video/other',
    'kind-specific usage label',
    'no play time/achievements/download where not applicable',
    'detail layout checks',
  ]);
});
