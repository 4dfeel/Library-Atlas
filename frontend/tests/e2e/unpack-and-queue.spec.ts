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
let unpacked: string;
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
    unpacked = join(root, '解压 フォルダ');
    archive = join(root, 'sample.zip');
    await rm(library, { recursive: true, force: true });
    await rm(unpacked, { recursive: true, force: true });
    await mkdir(library, { recursive: true });
    await mkdir(unpacked, { recursive: true });
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
    expect((await call('/settings/folders/extract', 'PUT', { path: unpacked })).status).toBe(200);
    await control({ download: { payload: archive }, gallery: null, upgrade: null });
  });

  test('one click: download, unpack, result, and the bar says so', async ({ page }) => {
    const work = await freshWork();
    await openWork(page, work);
    await expect(page.getByTestId('download-bar')).toBeVisible();
    await action(page).getByRole('button', { name: '下载并解压' }).click();
    await expect(action(page).getByTestId('extract-done')).toBeVisible({ timeout: 20_000 });
    await expect(action(page)).toContainText('已解压不代表已安装');
    await expect(page.getByText('已安装', { exact: true })).toHaveCount(0);
    await shot(page, 'unpacked');
    expect(await readdir(join(unpacked, work.sourceId, '音声'))).toEqual(['はじめに.txt']);
    expect(await readdir(join(library, work.sourceId))).toEqual([`${work.sourceId}.zip`]);
    await expect(page.getByTestId('download-bar')).toContainText('项已完成');
    await noHorizontalScroll(page);
  });

  test('download only stays download only, and can be unpacked later', async ({ page }) => {
    const work = await freshWork();
    await openWork(page, work);
    await action(page).getByRole('button', { name: '仅下载' }).click();
    await expect(action(page).getByTestId('download-done')).toBeVisible({ timeout: 20_000 });
    await expect(action(page).getByRole('button', { name: '解压', exact: true })).toBeVisible();
    await expect
      .poll(async () => readdir(join(unpacked, work.sourceId)).catch(() => [] as string[]))
      .toEqual([]);
    await action(page).getByRole('button', { name: '解压', exact: true }).click();
    await expect(action(page).getByTestId('extract-done')).toBeVisible({ timeout: 20_000 });
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
    expect(await readdir(join(library, work.sourceId))).toEqual([`${work.sourceId}.zip`]);
    await expect
      .poll(async () => readdir(unpacked).then((names) => names.includes(work.sourceId)))
      .toBe(false);
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
    expect(await readdir(join(library, work.sourceId))).toHaveLength(1);
    await row.getByRole('button', { name: '下载更新' }).click();
    await expect(row).toHaveCount(0, { timeout: 20_000 });
    await expect.poll(async () => (await readdir(join(library, work.sourceId))).length).toBe(2);
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

  test('a work with no images shows no empty frame', async ({ page }) => {
    await control({ gallery: 'none' });
    const work = await freshWork();
    await openWork(page, work);
    await expect(page.getByTestId('work-gallery')).toHaveCount(0);
    await expect(page.locator('.work-gallery')).toHaveCount(0);
  });
});
