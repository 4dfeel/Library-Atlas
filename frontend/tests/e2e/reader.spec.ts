import { expect, test, type Page } from '@playwright/test';
import { mkdir, rm, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { crc32, deflateSync } from 'node:zlib';
import { noHorizontalScroll, viewportTag } from './evidence';
import { enterRealMode, RealService } from './real-service';

/** Real API, real files and real rendering, checked by what the page's pixels and sizes say. */
const evidenceDir = resolve('../artifacts/phase-2-checkpoint-11');
const coreProjects = ['1080p', 'narrow', '4k-200'];

let service: RealService;
let token: string;
let place: string;

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

function pngChunk(kind: string, data: Buffer) {
  const typed = Buffer.concat([Buffer.from(kind), data]);
  const size = Buffer.alloc(4);
  size.writeUInt32BE(data.length);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(typed));
  return Buffer.concat([size, typed, crc]);
}

/** A page whose width says which page it is, so the test can tell what is really on screen. */
function png(width: number, height = 300): Buffer {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8;
  header[9] = 2;
  const row = Buffer.concat([Buffer.from([0]), Buffer.alloc(width * 3, 0x66)]);
  const rows = Buffer.concat(Array.from({ length: height }, () => row));
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    pngChunk('IHDR', header),
    pngChunk('IDAT', deflateSync(rows)),
    pngChunk('IEND', Buffer.alloc(0)),
  ]);
}

const pageWidth = (number: number) => 200 + number;

/** A stored (uncompressed) ZIP, written out by hand so nothing but this test is involved. */
function zip(members: [string, Buffer][]): Buffer {
  const locals: Buffer[] = [];
  const centrals: Buffer[] = [];
  let offset = 0;
  for (const [name, content] of members) {
    const nameBytes = Buffer.from(name);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0x800, 6);
    local.writeUInt32LE(crc32(content), 14);
    local.writeUInt32LE(content.length, 18);
    local.writeUInt32LE(content.length, 22);
    local.writeUInt16LE(nameBytes.length, 26);
    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(0x800, 8);
    central.writeUInt32LE(crc32(content), 16);
    central.writeUInt32LE(content.length, 20);
    central.writeUInt32LE(content.length, 24);
    central.writeUInt16LE(nameBytes.length, 28);
    central.writeUInt32LE(offset, 42);
    locals.push(local, nameBytes, content);
    centrals.push(central, nameBytes);
    offset += local.length + nameBytes.length + content.length;
  }
  const directory = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(members.length, 8);
  end.writeUInt16LE(members.length, 10);
  end.writeUInt32LE(directory.length, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, directory, end]);
}

/** Three blue pages, plus everything a PDF might try: a script on open, and a link off the machine. */
function pdf(pages: number): Buffer {
  const objects: string[] = [];
  const kids = Array.from({ length: pages }, (_, index) => `${4 + index * 2} 0 R`).join(' ');
  objects[1] =
    '<< /Type /Catalog /Pages 2 0 R /OpenAction << /S /JavaScript /JS (app.alert\\("danger"\\)) >> >>';
  objects[2] = `<< /Type /Pages /Kids [${kids}] /Count ${pages} >>`;
  objects[3] =
    '<< /Type /Annot /Subtype /Link /Rect [0 0 300 300] /A << /S /URI /URI (http://example.invalid/leak) >> >>';
  for (let index = 0; index < pages; index += 1) {
    const page = 4 + index * 2;
    const stream = `0 0 1 rg 20 20 ${100 + index} 100 re f`;
    objects[page] =
      `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Contents ${page + 1} 0 R /Annots [3 0 R] >>`;
    objects[page + 1] = `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`;
  }
  let body = '%PDF-1.4\n';
  const offsets: number[] = [];
  for (let id = 1; id < objects.length; id += 1) {
    offsets[id] = body.length;
    body += `${id} 0 obj\n${objects[id]}\nendobj\n`;
  }
  const xref = body.length;
  body += `xref\n0 ${objects.length}\n0000000000 65535 f \n`;
  for (let id = 1; id < objects.length; id += 1)
    body += `${String(offsets[id]).padStart(10, '0')} 00000 n \n`;
  body += `trailer\n<< /Size ${objects.length} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(body, 'latin1');
}

let next = 0;
async function work(build: (folder: string) => Promise<void>) {
  const listed = await (await call('/works?limit=100&kind=image')).json();
  const item = listed.items[next++ % listed.items.length];
  const linked = await (await call(`/works/${item.id}/local-copies`)).json();
  for (const copy of linked.copies) await call(`/local-copies/${copy.id}`, 'DELETE');
  const folder = join(place, `${test.info().project.name}-${next}`);
  await mkdir(folder, { recursive: true });
  await build(folder);
  await call(`/works/${item.id}/local-copies`, 'POST', { root: folder });
  return { item, folder };
}

async function volume(folder: string, name: string, pages: number) {
  await mkdir(join(folder, name), { recursive: true });
  for (let number = 1; number <= pages; number += 1)
    await writeFile(join(folder, name, `${number}.png`), png(pageWidth(number)));
}

/** The pages really on screen, in screen order, by their real decoded width. */
const shown = (page: Page) =>
  page.locator('.reader-spread img').evaluateAll((images) =>
    images.map((image) => {
      const element = image as HTMLImageElement;
      return element.complete ? element.naturalWidth : 0;
    }),
  );

async function expectShown(page: Page, numbers: number[]) {
  await expect.poll(() => shown(page)).toEqual(numbers.map(pageWidth));
}

test.describe('reading', () => {
  test.beforeAll(async () => {
    test.skip(!coreProjects.includes(test.info().project.name), 'core tiers only');
    test.setTimeout(120_000);
    service = await RealService.create(60, 8811);
    await service.start();
    place = join(service.dataDir, '..', '漫画 置き場');
    await rm(place, { recursive: true, force: true });
    await mkdir(place, { recursive: true });
    token = (await (await fetch(`${service.origin}/api/v1/session`)).json()).csrfToken;
  });
  test.afterAll(async () => service?.dispose());
  test.beforeEach(async ({ page }) => {
    await enterRealMode(page);
  });

  test('volumes stay apart; pages turn in natural order by button, key and click', async ({
    page,
  }) => {
    const { item } = await work(async (folder) => {
      await volume(folder, '第1巻', 12);
      await volume(folder, '第2巻', 2);
      await writeFile(join(folder, 'extra.rar'), 'Rar!');
    });
    await page.goto(`${service.origin}/library/${item.id}`);
    const panel = page.getByTestId('reader-panel');
    await expect(panel.getByTestId('reader-books').getByRole('button')).toHaveCount(2);
    await expect(panel.getByTestId('reader-unsupported')).toContainText('extra.rar');
    await shot(page, 'reader-panel');

    const opener = panel.getByTestId('reader-start');
    await opener.click();
    const reader = page.getByTestId('reader');
    await expect(reader.getByTestId('reader-count')).toHaveText('1 / 12');
    await expectShown(page, [1]);
    await shot(page, 'reader-single');
    await noHorizontalScroll(page);

    await reader.getByTestId('reader-right').click();
    await expectShown(page, [2]);
    await page.keyboard.press('ArrowRight');
    await expectShown(page, [3]);
    await page.keyboard.press('ArrowLeft');
    await expectShown(page, [2]);
    const stage = await reader.getByTestId('reader-stage').boundingBox();
    await page.mouse.click(stage!.x + stage!.width - 8, stage!.y + stage!.height / 2);
    await expectShown(page, [3]);
    // The middle of the screen is for looking, not turning.
    await page.mouse.click(stage!.x + stage!.width / 2, stage!.y + stage!.height / 2);
    await expectShown(page, [3]);

    // 10 follows 9, not 1.
    await reader.getByTestId('reader-seek').fill('10');
    await expectShown(page, [10]);
    await page.keyboard.press('Home');
    await expectShown(page, [1]);

    // Keys meant for a control are left to it.
    await reader.getByTestId('reader-mode').focus();
    await page.keyboard.press('Escape');
    await expect(reader).toBeVisible();
    await expectShown(page, [1]);

    await page.keyboard.press('Escape');
    await expect(reader).toHaveCount(0);
    await expect(opener.or(panel.getByTestId('reader-continue')).first()).toBeVisible();
  });

  test('the wheel turns pages: onward is down, a flick is one turn, tall pages scroll first', async ({
    page,
  }) => {
    const { item } = await work(async (folder) => {
      await volume(folder, '本', 5);
      await mkdir(join(folder, '長'));
      for (const number of [1, 2])
        await writeFile(join(folder, '長', `${number}.png`), png(pageWidth(number), 6000));
    });
    await page.goto(`${service.origin}/library/${item.id}`);
    const panel = page.getByTestId('reader-panel');
    await panel.getByRole('button', { name: '本', exact: true }).click();
    const reader = page.getByTestId('reader');
    await expectShown(page, [1]);
    const box = (await reader.getByTestId('reader-stage').boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    const rest = () => page.waitForTimeout(300);

    await page.mouse.wheel(0, 120);
    await expectShown(page, [2]);
    await rest();
    await page.mouse.wheel(0, -120);
    await expectShown(page, [1]);
    await rest();
    // Nothing before the first page.
    await page.mouse.wheel(0, -120);
    await rest();
    await expectShown(page, [1]);

    // A hard flick is one turn, not a run through the book.
    for (let i = 0; i < 5; i += 1) await page.mouse.wheel(0, 120);
    await rest();
    await expectShown(page, [2]);

    // A touchpad's small amounts add up.
    await page.mouse.wheel(0, 10);
    await rest();
    await expectShown(page, [2]);
    for (let i = 0; i < 5; i += 1) await page.mouse.wheel(0, 10);
    await expectShown(page, [3]);
    await rest();

    // Down is still onward when the book reads from the right.
    await reader.getByTestId('reader-direction').click();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.wheel(0, 120);
    await expectShown(page, [4]);
    await rest();
    await reader.getByTestId('reader-close').click();

    // A page taller than the view scrolls, and turns only once it has reached the bottom.
    await panel.getByRole('button', { name: '長', exact: true }).click();
    await expectShown(page, [1]);
    await reader.getByTestId('reader-fit').selectOption('width');
    const stage = reader.getByTestId('reader-stage');
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.wheel(0, 200);
    await expect.poll(() => stage.evaluate((node) => node.scrollTop)).toBeGreaterThan(0);
    await expect(reader.getByTestId('reader-count')).toHaveText('1 / 2');
    await stage.evaluate((node) => node.scrollTo({ top: node.scrollHeight }));
    await rest();
    await page.mouse.wheel(0, 200);
    await expect(reader.getByTestId('reader-count')).toHaveText('2 / 2');
    await expect.poll(() => stage.evaluate((node) => node.scrollTop)).toBe(0);
  });

  test('double pages pair correctly in both directions, keeping the place', async ({ page }) => {
    const { item } = await work((folder) => volume(folder, '本', 6));
    await page.goto(`${service.origin}/library/${item.id}`);
    await page.getByTestId('reader-panel').getByTestId('reader-start').click();
    const reader = page.getByTestId('reader');
    await reader.getByTestId('reader-mode').selectOption('double');
    await expectShown(page, [1]);
    await reader.getByTestId('reader-right').click();
    await expectShown(page, [2, 3]);
    await expect(reader.getByTestId('reader-count')).toHaveText('2-3 / 6');
    await shot(page, 'reader-double');
    await noHorizontalScroll(page);

    // Right to left: the place does not change, and the first page moves to the right.
    await reader.getByTestId('reader-direction').click();
    await expectShown(page, [3, 2]);
    await page.keyboard.press('ArrowLeft');
    await expectShown(page, [5, 4]);
    await page.keyboard.press('ArrowLeft');
    // A last odd page stands alone.
    await expectShown(page, [6]);
    await page.keyboard.press('ArrowLeft');
    await expectShown(page, [6]);
    await shot(page, 'reader-rtl-end');
  });

  test('a page is never cropped: it fits, can be widened, and can be zoomed', async ({ page }) => {
    const { item } = await work(async (folder) => {
      await mkdir(join(folder, '長'));
      await writeFile(join(folder, '長', '1.png'), png(pageWidth(1), 6000));
    });
    await page.goto(`${service.origin}/library/${item.id}`);
    await page.getByTestId('reader-panel').getByTestId('reader-start').click();
    const reader = page.getByTestId('reader');
    await expectShown(page, [1]);
    const stage = reader.getByTestId('reader-stage');
    const image = stage.locator('img');
    const stageBox = (await stage.boundingBox())!;
    const fitted = (await image.boundingBox())!;
    expect(fitted.height).toBeLessThanOrEqual(stageBox.height + 1);
    expect(fitted.width).toBeLessThanOrEqual(stageBox.width + 1);
    expect(await image.evaluate((node) => getComputedStyle(node).objectFit)).toBe('contain');

    await reader.getByTestId('reader-fit').selectOption('width');
    await expect
      .poll(async () => (await image.boundingBox())!.height)
      .toBeGreaterThan(stageBox.height);
    // All of it can be reached by scrolling.
    await expect
      .poll(() => stage.evaluate((node) => node.scrollHeight > node.clientHeight))
      .toBe(true);
    await shot(page, 'reader-fit-width');

    await reader.getByTestId('reader-zoom-in').click();
    await expect(reader.getByTestId('reader-fit')).toContainText('125%');
    await page.keyboard.press('Escape');
    await expect(reader.getByTestId('reader-fit')).toHaveValue('page');
    await expect(reader).toBeVisible();
  });

  test('the place, bookmarks and the read rule hold across a reload', async ({ page }) => {
    const { item } = await work((folder) => volume(folder, '本', 5));
    await page.goto(`${service.origin}/library/${item.id}`);
    const panel = page.getByTestId('reader-panel');
    await panel.getByTestId('reader-start').click();
    const reader = page.getByTestId('reader');
    await expectShown(page, [1]);
    await reader.getByTestId('reader-close').click();
    // Opening is not reading.
    await expect(panel.getByTestId('reader-books')).toContainText('5 页');

    await panel.getByTestId('reader-start').click();
    await reader.getByTestId('reader-seek').fill('3');
    await expectShown(page, [3]);
    await reader.getByTestId('reader-bookmark').click();
    await reader.getByTestId('reader-marks-toggle').click();
    await expect(reader.getByTestId('reader-marks')).toContainText('第 3 页');
    await shot(page, 'reader-bookmarks');
    await page.waitForTimeout(600);
    await page.reload();

    const resume = panel.getByTestId('reader-continue');
    await expect(resume).toContainText('第 3 页');
    await resume.click();
    await expectShown(page, [3]);
    await reader.getByTestId('reader-marks-toggle').click();
    await page.keyboard.press('End');
    await expectShown(page, [5]);
    await expect(reader.getByTestId('reader-read')).toHaveText('标为未读');
    await reader.getByTestId('reader-marks').getByRole('button', { name: '第 3 页' }).click();
    await expectShown(page, [3]);
    await page.waitForTimeout(500);
    await reader.getByTestId('reader-close').click();
    await expect(panel.getByTestId('reader-books')).toContainText('已读');
  });

  test('a changed page is said, not passed off as another; a bad page is only that page', async ({
    page,
  }) => {
    const { item, folder } = await work((target) => volume(target, '本', 4));
    await page.goto(`${service.origin}/library/${item.id}`);
    const panel = page.getByTestId('reader-panel');
    await panel.getByTestId('reader-start').click();
    const reader = page.getByTestId('reader');
    await reader.getByTestId('reader-seek').fill('2');
    await expectShown(page, [2]);
    await page.waitForTimeout(600);
    await reader.getByTestId('reader-close').click();

    await writeFile(join(folder, '本', '2.png'), png(999));
    await writeFile(join(folder, '本', '3.png'), 'not an image');
    // Past the short time the file list is kept.
    await page.waitForTimeout(31_000);
    await page.reload();
    await panel.getByTestId('reader-continue').click();
    await expect(reader.getByTestId('reader-notice')).toContainText('已经改变或不在');
    await expectShown(page, [1]);
    await reader.getByTestId('reader-seek').fill('3');
    await expect(reader.getByTestId('reader-page-problem')).toContainText('第 3 页无法显示');
    await shot(page, 'reader-bad-page');
    await reader.getByTestId('reader-seek').fill('4');
    await expectShown(page, [4]);
  });

  test('vertical reading follows the scroll and draws only what is near', async ({ page }) => {
    const { item } = await work((folder) => volume(folder, '縦', 30));
    await page.goto(`${service.origin}/library/${item.id}`);
    await page.getByTestId('reader-panel').getByTestId('reader-start').click();
    const reader = page.getByTestId('reader');
    await reader.getByTestId('reader-mode').selectOption('vertical');
    const stage = reader.getByTestId('reader-stage');
    await expect(stage.locator('img')).toHaveCount(30);
    await expect
      .poll(() =>
        stage
          .locator('img')
          .evaluateAll(
            (images) => images.filter((image) => (image as HTMLImageElement).complete).length,
          ),
      )
      .toBeGreaterThan(0);
    await reader.getByTestId('reader-seek').fill('20');
    await expect(reader.getByTestId('reader-count')).toHaveText('20 / 30');
    await expect
      .poll(() =>
        stage
          .locator('img[data-page="20"]')
          .evaluate((image) => (image as HTMLImageElement).naturalWidth),
      )
      .toBe(pageWidth(20));
    await stage.evaluate((node) => node.scrollBy(0, -node.clientHeight * 3));
    await expect.poll(() => reader.getByTestId('reader-count').textContent()).not.toBe('20 / 30');
    await shot(page, 'reader-vertical');
    await noHorizontalScroll(page);
  });

  test('a CBZ reads in place, sections and all', async ({ page }) => {
    const { item, folder } = await work((target) =>
      writeFile(
        join(target, '本.cbz'),
        zip([
          ['第一章/10.png', png(pageWidth(3))],
          ['第一章/2.png', png(pageWidth(2))],
          ['第一章/1.png', png(pageWidth(1))],
          ['第二章/1.png', png(pageWidth(4))],
          ['../../evil.png', png(pageWidth(9))],
        ]),
      ),
    );
    await page.goto(`${service.origin}/library/${item.id}`);
    await page.getByTestId('reader-panel').getByTestId('reader-start').click();
    const reader = page.getByTestId('reader');
    await expect(reader.getByTestId('reader-count')).toHaveText('1 / 4');
    await expectShown(page, [1]);
    await expect(reader.getByTestId('reader-notice')).toContainText('1 个文件没有打开');
    await reader.getByTestId('reader-seek').fill('3');
    await expectShown(page, [3]);
    await reader.getByTestId('reader-seek').fill('4');
    await expectShown(page, [4]);
    await expect(reader).toContainText('第二章');
    await shot(page, 'reader-cbz');
    // Nothing was unpacked beside it.
    const { readdir } = await import('node:fs/promises');
    expect(await readdir(folder)).toEqual(['本.cbz']);
  });

  test('a PDF really draws, from local files, and its script and link do nothing', async ({
    page,
  }) => {
    const { item } = await work((target) => writeFile(join(target, '本.pdf'), pdf(3)));
    const dialogs: string[] = [];
    const elsewhere: string[] = [];
    page.on('dialog', (dialog) => {
      dialogs.push(dialog.message());
      void dialog.dismiss();
    });
    page.on('request', (request) => {
      if (!request.url().startsWith(service.origin) && !request.url().startsWith('data:'))
        elsewhere.push(request.url());
    });
    const errors: string[] = [];
    page.on('console', (message) => {
      if (message.type() === 'error' && /Content Security Policy/.test(message.text()))
        errors.push(message.text());
    });
    await page.goto(`${service.origin}/library/${item.id}`);
    await page.getByTestId('reader-panel').getByTestId('reader-start').click();
    const reader = page.getByTestId('reader');
    await expect(reader.getByTestId('reader-count')).toHaveText('1 / 3', { timeout: 30_000 });
    const blue = () =>
      reader.locator('canvas').evaluate((node) => {
        const canvas = node as HTMLCanvasElement;
        const { data } = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height);
        for (let i = 0; i < data.length; i += 4)
          if (data[i] === 0 && data[i + 1] === 0 && data[i + 2] === 255) return true;
        return false;
      });
    await expect.poll(blue, { timeout: 15_000 }).toBe(true);
    await shot(page, 'reader-pdf');
    await reader.getByTestId('reader-right').click();
    await expect(reader.getByTestId('reader-count')).toHaveText('2 / 3');
    await expect.poll(blue, { timeout: 15_000 }).toBe(true);
    // Clicking where the PDF's link is goes nowhere.
    const box = (await reader.locator('canvas').boundingBox())!;
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    await page.waitForTimeout(300);
    expect(dialogs).toEqual([]);
    expect(elsewhere).toEqual([]);
    expect(errors).toEqual([]);
    await expect(page).toHaveURL(new RegExp(`^${service.origin}`));
  });

  test('a PDF that is not one is said, and the page survives', async ({ page }) => {
    const { item } = await work((target) => writeFile(join(target, '坏.pdf'), '%PDF-1.4\ngarbage'));
    await page.goto(`${service.origin}/library/${item.id}`);
    await page.getByTestId('reader-panel').getByTestId('reader-start').click();
    await expect(page.getByTestId('reader-book-problem')).toContainText('无法打开', {
      timeout: 30_000,
    });
    await shot(page, 'reader-bad-pdf');
    await page.getByRole('button', { name: '关闭阅读器' }).click();
    await expect(page.getByTestId('reader-panel')).toBeVisible();
  });
});
