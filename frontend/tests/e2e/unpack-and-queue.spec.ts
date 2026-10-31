import { expect, test, type Page } from '@playwright/test';
import { mkdir, readdir, rm, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { noHorizontalScroll, viewportTag } from './evidence';
import { enterRealMode, RealService } from './real-service';

/**
 * The real service, queues and archive code, with real sockets and real files. Only the
 * platform is the test profile's stand-in, and every image and archive is made up.
 */
const evidenceDir = resolve('../artifacts/phase-2-checkpoint-5');
const coreProjects = ['1080p', 'narrow', '4k-200'];
const MB = 1024 * 1024;

let service: RealService;
let library: string;
let archive: string;
let token: string;
let controlValues: Record<string, unknown> = {};

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

async function control(values: Record<string, unknown>) {
  controlValues = { ...controlValues, ...values };
  await writeFile(join(service.dataDir, 'fake-platform.json'), JSON.stringify(controlValues));
}

async function call(path: string, method = 'GET', body?: unknown) {
  return fetch(`${service.origin}/api/v1${path}`, {
    method,
    headers: { Origin: service.origin, 'X-Atlas-CSRF': token, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

async function sync() {
  const before = (await (await call('/sources/dlsite/sync')).json()).job?.id;
  await call('/sources/dlsite/sync', 'POST');
  await expect
    .poll(
      async () => {
        const job = (await (await call('/sources/dlsite/sync')).json()).job;
        return job && job.id !== before ? job.state : 'waiting';
      },
      { timeout: 30_000 },
    )
    .toBe('succeeded');
}

interface Work {
  id: string;
  sourceId: string;
  title: string;
}

async function locationOf(work: Work): Promise<string | null> {
  const { tasks } = await (await call('/extractions')).json();
  const task = tasks.find((entry: { workId: string }) => entry.workId === work.id);
  return task?.location ?? null;
}

let nextWork = 0;
async function freshWork(): Promise<Work> {
  const page = await (
    await call('/works?limit=100&search=' + encodeURIComponent('合成作品'))
  ).json();
  return page.items[nextWork++ % page.items.length];
}

async function openWork(page: Page, work: Work) {
  await page.goto(`${service.origin}/library/${encodeURIComponent(work.id)}`);
  await expect(page.getByTestId('download-action')).toBeVisible();
}

const action = (page: Page) => page.getByTestId('download-action');

/** A ZIP written by hand: one stored file, so no tool is needed to make it. */
function zipBytes(name: string, content: Buffer): Buffer {
  const crcTable = Array.from({ length: 256 }, (_, n) => {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    return c >>> 0;
  });
  let crc = 0xffffffff;
  for (const byte of content) crc = crcTable[(crc ^ byte) & 0xff]! ^ (crc >>> 8);
  crc = (crc ^ 0xffffffff) >>> 0;
  const fileName = Buffer.from(name, 'utf8');
  const shared = Buffer.alloc(26);
  shared.writeUInt16LE(20, 0);
  shared.writeUInt16LE(0x800, 2); // Names are UTF-8.
  shared.writeUInt32LE(crc, 10);
  shared.writeUInt32LE(content.length, 14);
  shared.writeUInt32LE(content.length, 18);
  shared.writeUInt16LE(fileName.length, 22);
  const local = Buffer.concat([Buffer.from([0x50, 0x4b, 3, 4]), shared, fileName, content]);
  const central = Buffer.concat([
    Buffer.from([0x50, 0x4b, 1, 2, 20, 0]),
    shared,
    Buffer.alloc(14),
    fileName,
  ]);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(1, 8);
  end.writeUInt16LE(1, 10);
  end.writeUInt32LE(central.length, 12);
  end.writeUInt32LE(local.length, 16);
  return Buffer.concat([local, central, end]);
}

test.describe('unpacking and the queue', () => {
  test.beforeAll(async () => {
    test.skip(!coreProjects.includes(test.info().project.name), 'core tiers only');
    test.setTimeout(120_000);
    service = await RealService.create(0, 8806);
    await service.start();
    const root = join(service.dataDir, '..');
    library = join(root, '作品 フォルダ');
    archive = join(root, 'sample.zip');
    await rm(library, { recursive: true, force: true });
    await mkdir(library, { recursive: true });
    await writeFile(archive, zipBytes('音声/はじめに.txt', Buffer.alloc(MB, 7)));
    token = (await (await fetch(`${service.origin}/api/v1/session`)).json()).csrfToken;
    await control({ size: 40, download: {} });
    await call('/sources/dlsite/login', 'POST', { loginId: 'ok@example.test', password: 'x' });
    await expect
      .poll(async () => (await (await call('/sources/dlsite/connection')).json()).state)
      .toBe('connected');
    await sync();
    nextWork = 0;
  });
  test.afterAll(async () => service?.dispose());
  test.beforeEach(async ({ page }) => {
    await enterRealMode(page);
    expect((await call('/settings/folders/library', 'PUT', { path: library })).status).toBe(200);
    await control({ download: { payload: archive }, gallery: null, intro: null, upgrade: null });
  });

  test('one click: download, unpack, result, and the bar says so', async ({ page }) => {
    const work = await freshWork();
    await openWork(page, work);
    await expect(page.getByTestId('download-bar')).toBeVisible();
    await action(page).getByRole('button', { name: '下载并解压' }).click();
    // Once it is here the page offers to use it, and no longer to download it.
    await expect(page.getByTestId('copy-uninstall')).toBeVisible({ timeout: 20_000 });
    await expect(action(page)).toHaveCount(0);
    await shot(page, 'unpacked');
    // Filed by type, maker and title, as the user files works by hand.
    const location = await locationOf(work);
    expect(location!.endsWith(join('虚构社团', work.title))).toBe(true);
    expect(await readdir(join(location!, '音声'))).toEqual(['はじめに.txt']);
    // Once unpacked, the archive is gone: the user wants no second copy.
    await expect
      .poll(async () =>
        readdir(join(library, 'Archives', work.sourceId)).catch(() => [] as string[]),
      )
      .toEqual([]);
    await expect(page.getByTestId('download-bar')).toContainText('项已完成');
    // One line for the work in the finished list, and a way to clear the list.
    await page.getByTestId('download-bar').click();
    const finished = page.getByTestId('downloads-page');
    await expect(
      finished.locator('[data-extract-task]').filter({ hasText: work.title }),
    ).toHaveCount(1);
    await expect(
      finished.locator('[data-download-task]').filter({ hasText: work.title }),
    ).toHaveCount(0);
    await shot(page, 'downloads-finished');
    await finished.getByTestId('clear-finished').click();
    await expect(finished.locator('[data-extract-task]')).toHaveCount(0);
    expect(await readdir(location!)).toEqual(['音声']);
    await noHorizontalScroll(page);
  });

  test('download only stays download only, and can be unpacked later', async ({ page }) => {
    const work = await freshWork();
    await openWork(page, work);
    await action(page).getByRole('button', { name: '仅下载' }).click();
    await expect(action(page).getByTestId('download-done')).toBeVisible({ timeout: 20_000 });
    await expect(action(page).getByRole('button', { name: '解压', exact: true })).toBeVisible();
    expect(await locationOf(work)).toBeNull();
    await action(page).getByRole('button', { name: '解压', exact: true }).click();
    await expect(page.getByTestId('copy-uninstall')).toBeVisible({ timeout: 20_000 });
    await expect(action(page)).toHaveCount(0);
  });

  test('a hostile archive is refused, and the download is kept', async ({ page }) => {
    const hostile = join(service.dataDir, '..', 'hostile.zip');
    await writeFile(hostile, zipBytes('../outside.txt', Buffer.from('x')));
    await control({ download: { payload: hostile } });
    const work = await freshWork();
    await openWork(page, work);
    await action(page).getByRole('button', { name: '下载并解压' }).click();
    await expect(action(page)).toContainText('不安全的路径', { timeout: 20_000 });
    await shot(page, 'unpack-refused');
    await expect(action(page).getByTestId('download-done')).toBeVisible();
    await expect(action(page).getByRole('button', { name: '重新解压' })).toBeVisible();
    expect(await readdir(join(library, 'Archives', work.sourceId))).toEqual([
      `${work.sourceId}.zip`,
    ]);
    expect(await locationOf(work)).toBeNull();
    expect(await readdir(join(library, '..'))).not.toContain('outside.txt');
  });

  test('the bar opens the queue page, with speed and sections', async ({ page }) => {
    await control({ download: { mode: 'slow', size: 32 * MB, delay: 0.03 } });
    const work = await freshWork();
    await openWork(page, work);
    await action(page).getByRole('button', { name: '仅下载' }).click();
    const bar = page.getByTestId('download-bar');
    await expect(bar).toContainText('下载中', { timeout: 10_000 });
    await shot(page, 'bar-running');
    await bar.click();
    await expect(page).toHaveURL(/\/downloads$/);
    const current = page.getByTestId('downloads-current');
    await expect(current).toBeVisible();
    await expect(page.getByTestId('downloads-speed')).toContainText('/s', { timeout: 10_000 });
    await expect(current).toContainText('估计剩余时间');
    await expect(current.getByRole('progressbar').first()).toHaveAttribute('aria-valuenow', /\d+/);
    await shot(page, 'downloads-page');
    await noHorizontalScroll(page);
    await current.getByRole('button', { name: '暂停' }).click();
    await expect(page.getByTestId('downloads-idle')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('downloads-page').getByText('已暂停')).toBeVisible();
    await page.getByTestId('downloads-page').getByRole('button', { name: '取消' }).first().click();
    await expect(page.getByTestId('downloads-page').getByText('已取消').first()).toBeVisible();
  });

  test('a newer version is offered, and only downloaded when asked', async ({ page }) => {
    await control({ download: { payload: archive } });
    const work = await freshWork();
    await openWork(page, work);
    await action(page).getByRole('button', { name: '仅下载' }).click();
    await expect(action(page).getByTestId('download-done')).toBeVisible({ timeout: 20_000 });
    await control({ upgrade: '2026-10-30T00:00:00+09:00' });
    await sync();
    await page.goto(`${service.origin}/downloads`);
    const row = page.locator(`[data-update="${work.id}"]`);
    await expect(row).toBeVisible();
    await expect(page.getByTestId('auto-check').getByRole('checkbox')).toBeChecked();
    await shot(page, 'update-available');
    await row.getByRole('button', { name: '下载更新' }).click();
    await expect(row).toHaveCount(0, { timeout: 20_000 });
    // Fetched and unpacked in one go, as any other download and unpack.
    await expect.poll(() => locationOf(work), { timeout: 20_000 }).not.toBeNull();
  });

  test('the store images: arrows, thumbnails, count, keyboard', async ({ page }) => {
    const work = await freshWork();
    await openWork(page, work);
    const gallery = page.getByTestId('work-gallery');
    await expect(gallery).toBeVisible();
    await gallery.scrollIntoViewIfNeeded();
    await expect(gallery).toContainText('共 6 张');
    const image = gallery.getByTestId('gallery-image');
    await expect(image).toHaveAttribute('src', /gallery\/0$/);
    await expect
      .poll(() => image.evaluate((node: HTMLImageElement) => node.naturalWidth))
      .toBeGreaterThan(0);
    // The first image stands upright: all of it must show, large and in its thumbnail.
    const fit = () =>
      image.evaluate((node: HTMLImageElement) => {
        const stage = node.parentElement!.getBoundingClientRect();
        const box = node.getBoundingClientRect();
        return {
          portrait: node.naturalHeight > node.naturalWidth,
          fit: getComputedStyle(node).objectFit,
          inside:
            box.top >= stage.top - 1 &&
            box.bottom <= stage.bottom + 1 &&
            box.left >= stage.left - 1 &&
            box.right <= stage.right + 1,
        };
      });
    await expect.poll(fit).toEqual({ portrait: true, fit: 'contain', inside: true });
    const thumbFit = await gallery
      .locator('.work-gallery-strip img')
      .first()
      .evaluate((node) => getComputedStyle(node).objectFit);
    expect(thumbFit).toBe('contain');
    await shot(page, 'gallery');
    await noHorizontalScroll(page);
    await gallery.getByRole('button', { name: '下一张' }).click();
    await expect(image).toHaveAttribute('src', /gallery\/1$/);
    await gallery.getByRole('button', { name: '第 5 张' }).click();
    await expect(image).toHaveAttribute('src', /gallery\/4$/);
    await page.keyboard.press('ArrowRight');
    await expect(image).toHaveAttribute('src', /gallery\/5$/);
    await gallery.getByRole('button', { name: '下一张' }).click();
    await expect(image).toHaveAttribute('src', /gallery\/0$/); // Wraps around.
    // The empty introduction was filled from the same record.
    await page.reload();
    await expect(page.locator('.about-text')).toContainText('合成的作品简介');
  });

  test('moving through the images never moves the page', async ({ page }) => {
    const work = await freshWork();
    await openWork(page, work);
    const gallery = page.getByTestId('work-gallery');
    await expect(gallery).toBeVisible();
    const scroller = page.locator('.detail-page');
    const top = () => scroller.evaluate((node) => node.scrollTop);
    const before = await top();
    // A strip too narrow for its thumbnails, so it has to follow the current one.
    const strip = gallery.locator('.work-gallery-strip');
    await strip.evaluate((node: HTMLElement) => {
      node.style.width = '200px';
    });
    const next = gallery.getByRole('button', { name: '下一张' });
    for (let step = 1; step <= 4; step++) {
      await next.evaluate((node: HTMLElement) => node.click());
      await expect(gallery.getByTestId('gallery-image')).toHaveAttribute(
        'src',
        new RegExp(`gallery/${step}$`),
      );
      expect(await top()).toBe(before);
      const shown = await strip.evaluate((node) => {
        const thumb = node.querySelector('[aria-current="true"]')!.getBoundingClientRect();
        const box = node.getBoundingClientRect();
        return thumb.left >= box.left - 1 && thumb.right <= box.right + 1;
      });
      expect(shown).toBe(true);
    }
  });

  test('the arrows answer a real press anywhere on them', async ({ page }) => {
    const work = await freshWork();
    await openWork(page, work);
    const gallery = page.getByTestId('work-gallery');
    await expect(gallery).toBeVisible();
    const image = gallery.getByTestId('gallery-image');
    const next = gallery.getByRole('button', { name: '下一张' });
    await next.scrollIntoViewIfNeeded();
    let expected = 0;
    // A real mouse, held a moment: a press that moves the button loses the click.
    for (const [across, down] of [
      [0.5, 0.12],
      [0.5, 0.5],
      [0.5, 0.88],
      [0.12, 0.5],
      [0.88, 0.5],
    ] as const) {
      const box = (await next.boundingBox())!;
      await page.mouse.move(box.x + box.width * across, box.y + box.height * down);
      await page.mouse.down();
      await page.waitForTimeout(150);
      await page.mouse.up();
      expected += 1;
      await expect(image).toHaveAttribute('src', new RegExp(`gallery/${expected}$`));
    }
  });

  test('the store button and the full introduction', async ({ page }) => {
    await control({ intro: null });
    const work = await freshWork();
    await openWork(page, work);
    const store = page.getByTestId('store-button');
    await expect(store).toHaveAttribute('href', new RegExp(`${work.sourceId}\\.html$`));
    await expect(store).toHaveAttribute('target', '_blank');
    await expect(store).toHaveAttribute('rel', /noopener/);
    const intro = page.getByTestId('official-intro');
    await intro.scrollIntoViewIfNeeded();
    await expect(intro).toContainText('合成的第一节');
    await expect(intro).toContainText('合成的第二节');
    await expect(intro).toContainText('特点二');
    await expect(intro).toContainText('容量');
    // A dangerous link is left as plain text, and no script arrived.
    await expect(intro.getByRole('link', { name: '危险链接' })).toHaveCount(0);
    await expect(intro.getByRole('link', { name: '官方链接' })).toHaveAttribute('target', '_blank');
    await expect(intro.getByTestId('intro-video')).toContainText('前往官方页面');
    // The tall image keeps its shape, and its width stays within the reading column.
    const tall = intro.getByRole('button', { name: /合成长图/ }).locator('img');
    await tall.scrollIntoViewIfNeeded();
    await expect
      .poll(() => tall.evaluate((node: HTMLImageElement) => node.naturalHeight))
      .toBe(2400);
    const shape = await tall.evaluate(
      (node: HTMLImageElement) => node.clientHeight / node.clientWidth,
    );
    expect(shape).toBeCloseTo(6, 0);
    await shot(page, 'introduction');
    await noHorizontalScroll(page);
    // Enlarging, and Escape back to where it was.
    await intro.getByRole('button', { name: /合成说明图/ }).click();
    await expect(page.getByTestId('intro-lightbox')).toBeVisible();
    await shot(page, 'introduction-enlarged');
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('intro-lightbox')).toHaveCount(0);
  });

  test('the banner is a frosted store image, a wide one, and never the cover', async ({ page }) => {
    await control({ intro: null, gallery: null });
    const work = await freshWork();
    await openWork(page, work);
    const banner = page.locator('[data-backdrop="store"] img');
    await expect(banner).toHaveAttribute('src', /\/gallery\/\d+/);
    await expect
      .poll(() => banner.evaluate((node: HTMLImageElement) => node.naturalWidth))
      .toBeGreaterThan(0);
    // Among the store's images the first stands upright: a wide banner never picks that one.
    await expect
      .poll(() =>
        banner.evaluate(
          (node: HTMLImageElement) =>
            node.naturalWidth > 0 && node.naturalWidth >= node.naturalHeight,
        ),
      )
      .toBe(true);
    expect(await banner.evaluate((node) => getComputedStyle(node).filter)).toContain('blur');
    const covers = await page
      .locator('.hero-cover img')
      .evaluateAll((nodes) => nodes.map((node) => node.getAttribute('src')));
    expect(covers).not.toContain(await banner.getAttribute('src'));
    await shot(page, 'store-banner');
    await noHorizontalScroll(page);
    // Different visits can land on different images, each one of the work's own.
    const seen = new Set<string>();
    for (let visit = 0; visit < 12; visit += 1) {
      await page.reload();
      seen.add((await banner.getAttribute('src'))!);
    }
    expect(seen.size).toBeGreaterThan(1);
    // No store images: the pattern, not the cover.
    await control({ gallery: 'none' });
    const bare = await freshWork();
    await openWork(page, bare);
    await expect(page.locator('[data-backdrop="pattern"]')).toBeVisible();
    await expect(page.locator('[data-backdrop="store"]')).toHaveCount(0);
    await control({ gallery: null });
  });

  test('the store page video plays here, and nothing is asked of its host until play', async ({
    page,
  }) => {
    await control({
      intro: null,
      trailer: [
        {
          file_type: 'video',
          embed_url: 'https://chobit.cc/embed/synthetic/player?dlsite=1',
          thumb: 'https://file.chobit.cc/contents/synthetic_thumb.jpg?w=560&h=420',
          embed_width: 560,
          embed_height: 347,
        },
      ],
    });
    const asked: string[] = [];
    await page.route('https://chobit.cc/**', (route) => {
      asked.push(route.request().url());
      return route.fulfill({
        contentType: 'text/html',
        body: '<!doctype html><video data-testid="synthetic-player"></video>',
      });
    });
    const work = await freshWork();
    await openWork(page, work);
    const intro = page.getByTestId('official-intro');
    await intro.scrollIntoViewIfNeeded();
    const player = intro.getByTestId('intro-player');
    await expect(player.locator('img')).toHaveJSProperty('complete', true);
    await expect
      .poll(() => player.locator('img').evaluate((node: HTMLImageElement) => node.naturalWidth))
      .toBeGreaterThan(0);
    expect(asked).toEqual([]);
    await shot(page, 'intro-player');
    await noHorizontalScroll(page);
    await player.getByRole('button', { name: '播放预览视频' }).click();
    const frame = page.frameLocator('[data-testid="intro-player"] iframe');
    await expect(frame.getByTestId('synthetic-player')).toBeAttached();
    expect(asked).toEqual(['https://chobit.cc/embed/synthetic/player?dlsite=1']);
    await control({ trailer: null });
  });

  test('without a readable page the rest of the work still stands', async ({ page }) => {
    await control({ intro: 'changed' });
    const work = await freshWork();
    await openWork(page, work);
    const intro = page.getByTestId('official-intro');
    await expect(intro).toContainText('和预期不同');
    await expect(page.getByTestId('download-action')).toBeVisible();
    await expect(page.getByTestId('store-button')).toBeVisible();
    await shot(page, 'introduction-unavailable');
    await control({ intro: null });
    await intro.getByRole('button', { name: '刷新' }).click();
    await expect(intro).toContainText('合成的第一节');
  });

  test('a work with no images shows no empty frame', async ({ page }) => {
    await control({ gallery: 'none' });
    const work = await freshWork();
    await openWork(page, work);
    await expect(page.getByTestId('work-gallery')).toHaveCount(0);
    await expect(page.locator('.work-gallery')).toHaveCount(0);
  });
});
