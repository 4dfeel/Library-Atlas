import { expect, test, type Page } from '@playwright/test';
import { mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { noHorizontalScroll, viewportTag } from './evidence';
import { enterRealMode, RealService } from './real-service';

/** Real API, queue and file operations, on made-up folders and saves. No real game is involved. */
const evidenceDir = resolve('../artifacts/phase-2-checkpoint-9');
const coreProjects = ['1080p', 'narrow', '4k-200'];

let service: RealService;
let token: string;
let place: string;
let archive: string;

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

function zipOne(name: string, content: Buffer): Buffer {
  const table = Array.from({ length: 256 }, (_, n) => {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    return c >>> 0;
  });
  let crc = 0xffffffff;
  for (const byte of content) crc = table[(crc ^ byte) & 0xff]! ^ (crc >>> 8);
  crc = (crc ^ 0xffffffff) >>> 0;
  const fileName = Buffer.from(name, 'utf8');
  const shared = Buffer.alloc(26);
  shared.writeUInt16LE(20, 0);
  shared.writeUInt16LE(0x800, 2);
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

test.describe('updating a game', () => {
  test.beforeAll(async () => {
    test.skip(!coreProjects.includes(test.info().project.name), 'core tiers only');
    test.setTimeout(120_000);
    service = await RealService.create(0, 8809);
    await service.start();
    place = join(service.dataDir, '..', 'ゲーム 置き場');
    await rm(place, { recursive: true, force: true });
    await mkdir(place, { recursive: true });
    archive = join(place, 'new.zip');
    await writeFile(archive, zipOne('Game.exe', Buffer.from('new program')));
    token = (await (await fetch(`${service.origin}/api/v1/session`)).json()).csrfToken;
    await writeFile(
      join(service.dataDir, 'fake-platform.json'),
      JSON.stringify({ size: 30, download: { payload: archive } }),
    );
    await call('/sources/dlsite/login', 'POST', { loginId: 'ok@example.test', password: 'x' });
    await expect
      .poll(async () => (await (await call('/sources/dlsite/connection')).json()).state)
      .toBe('connected');
    await call('/sources/dlsite/sync', 'POST');
    await expect
      .poll(async () => (await (await call('/sources/dlsite/sync')).json()).job?.state, {
        timeout: 30_000,
      })
      .toBe('succeeded');
    await call('/settings/folders/library', 'PUT', { path: join(place, 'works') }).catch(
      () => null,
    );
    await mkdir(join(place, 'works'), { recursive: true });
    await call('/settings/folders/library', 'PUT', { path: join(place, 'works') });
  });
  test.afterAll(async () => service?.dispose());

  test('saves first, the new version in place, the old one kept until confirmed', async ({
    page,
  }) => {
    await enterRealMode(page);
    const name = test.info().project.name;
    const game = join(place, `game-${name}`);
    await mkdir(join(game, 'save'), { recursive: true });
    await writeFile(join(game, 'Game.exe'), 'old program');
    await writeFile(join(game, 'outdated.dll'), 'old');
    await writeFile(join(game, 'save', 'slot1.sav'), 'my progress');
    const list = await (
      await call('/works?limit=100&kind=game&search=' + encodeURIComponent('合成作品'))
    ).json();
    const work = list.items[['1080p', 'narrow', '4k-200'].indexOf(name)];
    await call(`/works/${work.id}/local-copies`, 'POST', { root: game, entry: 'Game.exe' });

    await page.goto(`${service.origin}/library/${work.id}`);
    const panel = page.getByTestId('game-update');
    await panel.getByRole('button', { name: '更新本体' }).click();
    const form = page.getByTestId('update-form');
    // Nothing starts until the saves are answered for and the game is said to be closed.
    await expect(form.getByRole('button', { name: '开始更新' })).toBeDisabled();
    await form.getByRole('button', { name: '添加存档位置' }).click();
    await form.getByLabel('存档路径').fill('save');
    await form.getByLabel('游戏已经关闭').check();
    await shot(page, 'update-form');
    await noHorizontalScroll(page);
    await form.getByRole('button', { name: '开始更新' }).click();

    const waiting = panel.getByTestId('update-waiting');
    await expect(waiting).toBeVisible({ timeout: 30_000 });
    await expect(waiting.getByTestId('update-extras')).toContainText('outdated.dll');
    await shot(page, 'update-waiting');
    expect(await readFile(join(game, 'Game.exe'), 'utf8')).toBe('new program');
    expect(await readFile(join(game, 'save', 'slot1.sav'), 'utf8')).toBe('my progress');
    expect((await readdir(place)).filter((item) => item.includes(`game-${name}`))).toHaveLength(2);

    await waiting.getByRole('button', { name: '没问题，清理旧版本' }).click();
    await expect(panel).toContainText('已更新');
    expect((await readdir(place)).filter((item) => item.includes(`game-${name}`))).toEqual([
      `game-${name}`,
    ]);
    expect(await readFile(join(game, 'save', 'slot1.sav'), 'utf8')).toBe('my progress');

    await panel.getByRole('button', { name: '更新本体' }).click();
    await expect(page.getByTestId('save-backups')).toContainText('1 个文件');
    await shot(page, 'update-backups');
  });
});
