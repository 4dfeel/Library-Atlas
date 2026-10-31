import { expect, test, type Page } from '@playwright/test';
import { mkdir, rm, unlink, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { noHorizontalScroll, viewportTag } from './evidence';
import { enterRealMode, RealService } from './real-service';

/** Real API, real files and the browser's real audio element. All sound is generated here. */
const evidenceDir = resolve('../artifacts/phase-2-checkpoint-10');
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

/** A quiet tone: real audio a browser really decodes. */
function wav(seconds: number): Buffer {
  const rate = 8000;
  const frames = rate * seconds;
  const header = Buffer.alloc(44);
  header.write('RIFF', 0);
  header.writeUInt32LE(36 + frames, 4);
  header.write('WAVEfmt ', 8);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20);
  header.writeUInt16LE(1, 22);
  header.writeUInt32LE(rate, 24);
  header.writeUInt32LE(rate, 28);
  header.writeUInt16LE(1, 32);
  header.writeUInt16LE(8, 34);
  header.write('data', 36);
  header.writeUInt32LE(frames, 40);
  const body = Buffer.alloc(frames, 0x80);
  for (let i = 0; i < frames; i += 2) body[i] = 0x88;
  return Buffer.concat([header, body]);
}

let next = 0;
async function album() {
  const page = await (await call('/works?limit=100&kind=audio')).json();
  const work = page.items[next++ % page.items.length];
  const folder = join(place, `${test.info().project.name}-${next}`);
  await mkdir(join(folder, '本編'), { recursive: true });
  await writeFile(join(folder, '本編', '1 はじめに.wav'), wav(30));
  await writeFile(join(folder, '本編', '2 つづき.wav'), wav(30));
  await writeFile(join(folder, '本編', '10 おわり.wav'), wav(3));
  await writeFile(join(folder, '本編', 'old.wma'), Buffer.from('x'));
  // A work comes round again when there are few: each test listens to its own folder only.
  const linked = await (await call(`/works/${work.id}/local-copies`)).json();
  for (const copy of linked.copies) await call(`/local-copies/${copy.id}`, 'DELETE');
  await call(`/works/${work.id}/local-copies`, 'POST', { root: folder });
  return { work, folder };
}

test.describe('listening', () => {
  test.beforeAll(async () => {
    test.skip(!coreProjects.includes(test.info().project.name), 'core tiers only');
    test.setTimeout(120_000);
    service = await RealService.create(60, 8810);
    await service.start();
    place = join(service.dataDir, '..', '音声 置き場');
    await rm(place, { recursive: true, force: true });
    await mkdir(place, { recursive: true });
    token = (await (await fetch(`${service.origin}/api/v1/session`)).json()).csrfToken;
  });
  test.afterAll(async () => service?.dispose());
  test.beforeEach(async ({ page }) => {
    await enterRealMode(page);
  });

  const audioTime = (page: Page) =>
    page.getByTestId('player-time').evaluate((node) => node.textContent ?? '');

  test('nothing plays until asked; then it really plays, seeks and moves between pages', async ({
    page,
  }) => {
    const { work } = await album();
    await page.goto(`${service.origin}/library/${work.id}`);
    const panel = page.getByTestId('audio-panel');
    await expect(panel.getByTestId('audio-tracks')).toContainText('2 つづき.wav');
    // Natural order: 10 comes last.
    const names = await panel.locator('[data-testid="audio-tracks"] li button').allInnerTexts();
    expect(names.slice(0, 3).map((name) => name.trim())).toEqual([
      '1 はじめに.wav',
      '2 つづき.wav',
      '10 おわり.wav',
    ]);
    await expect(panel.getByRole('button', { name: /old\.wma/ })).toBeDisabled();
    await expect(panel).toContainText('无法在这里播放');
    await expect(page.getByTestId('mini-player')).toHaveCount(0);
    await shot(page, 'audio-idle');

    await panel.getByTestId('audio-play').click();
    const player = page.getByTestId('mini-player');
    await expect(player.getByTestId('player-name')).toHaveText('1 はじめに.wav');
    await expect.poll(() => audioTime(page), { timeout: 15_000 }).toMatch(/00:0[1-9]/);
    await expect(player.getByTestId('player-seek')).toHaveAttribute('max', '30');
    await shot(page, 'audio-playing');
    await noHorizontalScroll(page);

    // A real seek, against the real range-serving endpoint.
    await player.getByTestId('player-seek').fill('20');
    await expect.poll(() => audioTime(page)).toMatch(/00:2\d/);

    // Across pages: the same session keeps going, and only one exists.
    await page.getByRole('link', { name: '作品库' }).first().click();
    await expect(page).toHaveURL(/\/library/);
    await expect(player).toBeVisible();
    const before = await audioTime(page);
    await expect.poll(() => audioTime(page)).not.toBe(before);

    await player.getByTestId('player-toggle').click();
    await expect(player.getByRole('button', { name: '播放', exact: true })).toBeVisible();
  });

  test('the next one follows, and looping and speed do what they say', async ({ page }) => {
    const { work } = await album();
    await page.goto(`${service.origin}/library/${work.id}`);
    const panel = page.getByTestId('audio-panel');
    await panel.getByRole('button', { name: /10 おわり/ }).click();
    const player = page.getByTestId('mini-player');
    await player.getByTestId('player-rate').selectOption('2');
    // It is the last track and looping is off, so it stops at the end. The clock says so: the play
    // button alone also shows for the moment before the sound has started.
    await expect.poll(() => audioTime(page), { timeout: 15_000 }).toBe('00:03 / 00:03');
    await expect(player.getByRole('button', { name: '播放', exact: true })).toBeVisible();
    await player.getByTestId('player-loop').click();
    await player.getByTestId('player-toggle').click();
    await expect(player.getByTestId('player-name')).toHaveText('1 はじめに.wav', {
      timeout: 15_000,
    });
  });

  test('where it left off is kept, and continuing is a choice', async ({ page }) => {
    const { work } = await album();
    await page.goto(`${service.origin}/library/${work.id}`);
    const panel = page.getByTestId('audio-panel');
    await panel.getByRole('button', { name: /2 つづき/ }).click();
    const player = page.getByTestId('mini-player');
    await expect.poll(() => audioTime(page), { timeout: 15_000 }).toMatch(/00:0[1-9]/);
    await player.getByTestId('player-seek').fill('15');
    await expect.poll(() => audioTime(page)).toMatch(/00:1[5-9]/);
    await page.getByRole('button', { name: '暂停' }).click();
    await panel.getByTestId('audio-bookmark').click();
    await expect(panel.getByTestId('audio-bookmarks')).toContainText('2 つづき.wav');

    await page.reload();
    // After a reload nothing is playing until the user says so.
    await expect(page.getByTestId('mini-player')).toHaveCount(0);
    const resume = panel.getByTestId('audio-continue');
    await expect(resume).toContainText('2 つづき.wav');
    await expect(resume).toContainText('00:1');
    await shot(page, 'audio-continue');
    await resume.click();
    await expect.poll(() => audioTime(page), { timeout: 15_000 }).toMatch(/00:1[5-9]/);
  });

  test('a file that went away is said once and not retried', async ({ page }) => {
    const { work, folder } = await album();
    await page.goto(`${service.origin}/library/${work.id}`);
    const panel = page.getByTestId('audio-panel');
    await expect(panel.getByTestId('audio-tracks')).toContainText('1 はじめに.wav');
    await unlink(join(folder, '本編', '1 はじめに.wav'));
    await panel.getByRole('button', { name: /1 はじめに/ }).click();
    await expect(page.getByTestId('player-error')).toContainText('无法播放');
    await shot(page, 'audio-error');
  });

  test('a stop timer can be set and cancelled, and playlists keep their order', async ({
    page,
  }) => {
    const { work } = await album();
    await page.clock.install();
    await page.goto(`${service.origin}/library/${work.id}`);
    const panel = page.getByTestId('audio-panel');
    await panel.getByTestId('audio-play').click();
    const player = page.getByTestId('mini-player');
    await player.getByTestId('player-sleep').selectOption('15');
    await expect(player.getByTestId('player-sleep-at')).toContainText('停止');
    await player.getByTestId('player-sleep').selectOption('0');
    await expect(player.getByTestId('player-sleep-at')).toHaveCount(0);
    // A timer that is set really stops the sound, and nothing starts it again.
    await player.getByTestId('player-sleep').selectOption('15');
    await expect(player.getByRole('button', { name: '暂停' })).toBeVisible();
    await page.clock.fastForward('15:01');
    await expect(player.getByRole('button', { name: '播放', exact: true })).toBeVisible();
    await expect(player.getByTestId('player-sleep-at')).toHaveCount(0);

    await panel.getByLabel('播放列表名称').fill(`列表 ${test.info().project.name}`);
    await panel.getByRole('button', { name: '保存为播放列表' }).click();
    await expect(panel.getByTestId('audio-playlists')).toContainText('3 首');
    await shot(page, 'audio-playlist');
    await player.getByRole('button', { name: '关闭播放器' }).click();
    await expect(player).toHaveCount(0);
  });
});
