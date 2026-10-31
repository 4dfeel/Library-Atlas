import { expect, test, type Page } from '@playwright/test';
import { access, mkdir, readFile, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { noHorizontalScroll, viewportTag } from './evidence';
import { RealService } from './real-service';

/**
 * Two real services sharing one made-up Drive, as two computers do, with real files and the real
 * adapter code. The Google side is the stand-in: nothing here reaches Google, or starts a program.
 */
const evidenceDir = resolve('../artifacts/checkpoint-9b');
const coreProjects = ['1080p', 'narrow', '4k-200'];

let one: RealService;
let two: RealService;
let tokens: Map<RealService, string>;

async function shot(page: Page, name: string) {
  const info = test.info();
  const dir = resolve(evidenceDir, 'screenshots', info.project.name);
  await mkdir(dir, { recursive: true });
  await page.screenshot({
    path: resolve(dir, `${name}__${viewportTag(page, info)}.png`),
    animations: 'disabled',
  });
}

const call = (service: RealService, path: string, method = 'GET', body?: unknown) =>
  fetch(`${service.origin}/api/v1${path}`, {
    method,
    headers: {
      Origin: service.origin,
      'X-Atlas-CSRF': tokens.get(service)!,
      'Content-Type': 'application/json',
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

/** Plays the user's browser: Google says yes and sends them back to the address Atlas gave. */
async function approve(service: RealService, answer: Record<string, string> = { code: 'good' }) {
  const url = new URL(await readFile(join(service.dataDir, 'fake-browser-url'), 'utf-8'));
  const back = new URL(url.searchParams.get('redirect_uri')!);
  back.searchParams.set('state', url.searchParams.get('state')!);
  for (const [key, value] of Object.entries(answer)) back.searchParams.set(key, value);
  return fetch(back);
}

let next = 0;
/** The same work on both computers, each with its own folder and its own save. */
async function shared() {
  next += 1;
  const listed = await (await call(one, '/works?limit=100&platform=dlsite&kind=game')).json();
  const first = listed.items[next % listed.items.length];
  const other = (
    await (await call(two, `/works?limit=100&platform=dlsite&kind=game`)).json()
  ).items.find((item: { sourceId: string }) => item.sourceId === first.sourceId);
  const prepare = async (service: RealService, workId: string, label: string) => {
    const folder = join(service.dataDir, '..', `游戏 ${test.info().project.name} ${next} ${label}`);
    await mkdir(join(folder, 'save'), { recursive: true });
    await writeFile(join(folder, 'Game.exe'), 'not run');
    await call(service, `/works/${workId}/local-copies`, 'POST', {
      root: folder,
      entry: 'Game.exe',
    });
    await call(service, `/works/${workId}/save-config`, 'PUT', {
      rules: [{ kind: 'inside', path: 'save' }],
      confirmedNone: false,
    });
    return join(folder, 'save', 'slot1.dat');
  };
  return {
    first: { id: first.id as string, save: await prepare(one, first.id, 'A') },
    second: { id: other.id as string, save: await prepare(two, other.id, 'B') },
  };
}

const panel = (page: Page) => page.getByTestId('cloud-save');
const expectState = (page: Page, state: string) =>
  expect(panel(page)).toHaveAttribute('data-state', state, { timeout: 20_000 });

test.describe('cloud saves', () => {
  test.beforeAll(async () => {
    test.skip(!coreProjects.includes(test.info().project.name), 'core tiers only');
    test.setTimeout(180_000);
    const name = test.info().project.name;
    one = await RealService.create(60, 8813);
    two = await RealService.create(60, 8814);
    const drive = join(one.dataDir, '..', `共有 Drive ${name}`);
    await mkdir(drive, { recursive: true });
    process.env.ATLAS_FAKE_DRIVE_DIR = drive;
    await one.start();
    await two.start();
    delete process.env.ATLAS_FAKE_DRIVE_DIR;
    tokens = new Map();
    for (const service of [one, two]) {
      tokens.set(
        service,
        (await (await fetch(`${service.origin}/api/v1/session`)).json()).csrfToken,
      );
    }
    await call(two, '/cloud/client', 'PUT', { clientId: 'client.apps.googleusercontent.com' });
    await call(two, '/cloud/connect', 'POST');
    await approve(two);
  });
  test.afterAll(async () => {
    await one?.dispose();
    await two?.dispose();
  });
  test.beforeEach(async ({ page }) => {
    page.on('request', (request) => {
      expect(request.url()).not.toMatch(/googleapis|accounts\.google/);
    });
  });

  test('connecting: the steps, a refusal, and then connected, with no secret on the page', async ({
    page,
  }) => {
    await page.goto(`${one.origin}/settings`);
    const settings = page.getByTestId('cloud-panel');
    await settings.scrollIntoViewIfNeeded();
    await expect(settings).toContainText('console.cloud.google.com');
    await expect(settings.getByTestId('cloud-connect')).toBeDisabled();
    await shot(page, 'cloud-setup');
    await noHorizontalScroll(page);

    await settings.getByLabel('客户端 ID').fill('client.apps.googleusercontent.com');
    await settings.getByTestId('cloud-connect').click();
    await expect(settings.getByTestId('cloud-connecting')).toBeVisible();
    await approve(one, { error: 'access_denied' });
    await expect(settings.getByTestId('cloud-problem')).toContainText('取消');

    await settings.getByTestId('cloud-connect').click();
    await expect(settings.getByTestId('cloud-connecting')).toBeVisible();
    await approve(one);
    await expect(settings.getByTestId('cloud-connected')).toContainText('合成账号', {
      timeout: 15_000,
    });
    await expect(settings).not.toContainText('refresh');
    await shot(page, 'cloud-connected');
  });

  test('a save goes up, the other computer takes it, and a new one comes back', async ({
    page,
  }) => {
    const { first, second } = await shared();
    await writeFile(first.save, 'from computer one');
    await page.goto(`${one.origin}/library/${first.id}`);
    await expectState(page, 'local_only');
    await shot(page, 'cloud-local-only');
    await panel(page).getByTestId('cloud-backup').click();
    await expectState(page, 'synced');
    await expect(panel(page).getByTestId('cloud-state')).toContainText('已同步');
    await shot(page, 'cloud-synced');

    await page.goto(`${two.origin}/library/${second.id}`);
    await expectState(page, 'cloud_update');
    await panel(page).getByTestId('cloud-restore-open').click();
    const dialog = page.getByTestId('cloud-restore');
    await expect(dialog).toContainText('合成电脑');
    await expect(dialog.getByTestId('cloud-use').first()).toBeDisabled();
    await shot(page, 'cloud-restore');
    await dialog.getByTestId('cloud-closed').check();
    await dialog.getByTestId('cloud-use').first().click();
    await expectState(page, 'synced');
    expect(await readFile(second.save, 'utf-8')).toBe('from computer one');

    await writeFile(second.save, 'from computer two');
    await page.reload();
    await expectState(page, 'local_changed');
    await panel(page).getByTestId('cloud-backup').click();
    await expectState(page, 'synced');

    await page.goto(`${one.origin}/library/${first.id}`);
    await expectState(page, 'cloud_update');
    await panel(page).getByTestId('cloud-history-open').click();
    await expect(page.getByTestId('cloud-restore').locator('li')).toHaveCount(2);
    await noHorizontalScroll(page);
  });

  test('both changed: a conflict is shown, nothing is overwritten, and choosing settles it', async ({
    page,
  }) => {
    const { first, second } = await shared();
    await writeFile(first.save, 'shared start');
    await call(one, `/works/${first.id}/cloud/backup`, 'POST');
    await page.goto(`${one.origin}/library/${first.id}`);
    await expectState(page, 'synced');
    const history = (await (await call(two, `/works/${second.id}/cloud`)).json()).history;
    await call(two, `/works/${second.id}/cloud/restore`, 'POST', {
      snapshotId: history[0].id,
      confirmClosed: true,
    });
    await writeFile(first.save, 'branch of one');
    await writeFile(second.save, 'branch of two');
    await call(one, `/works/${first.id}/cloud/backup`, 'POST');
    await call(two, `/works/${second.id}/cloud/backup`, 'POST');

    await page.goto(`${one.origin}/library/${first.id}`);
    await expectState(page, 'conflict');
    await panel(page).getByTestId('cloud-conflict-open').click();
    const dialog = page.getByTestId('cloud-restore');
    await expect(dialog.getByTestId('cloud-use')).toHaveCount(2);
    await shot(page, 'cloud-conflict');
    expect(await readFile(first.save, 'utf-8')).toBe('branch of one');
    await dialog.getByTestId('cloud-keep-local').click();
    await expectState(page, 'synced');
    expect(await readFile(first.save, 'utf-8')).toBe('branch of one');
    // The other computer's own save is still its own until its owner says otherwise.
    expect(await readFile(second.save, 'utf-8')).toBe('branch of two');
    await page.goto(`${two.origin}/library/${second.id}`);
    await expectState(page, 'cloud_update');
  });

  test('asked to check first, a start says what the cloud holds, and nothing starts', async ({
    page,
  }) => {
    const { first, second } = await shared();
    await writeFile(second.save, 'newer on the other computer');
    await call(two, `/works/${second.id}/cloud/backup`, 'POST');
    await expect
      .poll(async () => (await (await call(one, `/works/${first.id}/cloud`)).json()).state, {
        timeout: 20_000,
      })
      .toBe('cloud_update');
    await page.goto(`${one.origin}/library/${first.id}`);
    await expectState(page, 'cloud_update');
    await call(one, '/cloud/options', 'PUT', { autoCheck: true, autoBackup: false });
    await page.reload();
    await page.getByTestId('launch').click();
    const asked = page.getByTestId('cloud-before-start');
    await expect(asked).toBeVisible();
    await shot(page, 'cloud-before-start');
    await asked.getByRole('button', { name: '先不启动' }).click();
    await expect(asked).toHaveCount(0);
    await call(one, '/cloud/options', 'PUT', { autoCheck: false, autoBackup: false });
    // Nothing was restored behind the user's back.
    await expect(access(first.save)).rejects.toThrow();
  });

  test('where to look comes first', async ({ page }) => {
    const { first } = await shared();
    await call(one, `/works/${first.id}/save-config`, 'PUT', { rules: [], confirmedNone: false });
    await page.goto(`${one.origin}/library/${first.id}`);
    await expectState(page, 'unconfigured');
    await panel(page).getByTestId('cloud-configure').click();
    const dialog = page.getByTestId('cloud-config');
    await dialog.getByLabel('存档路径').fill('save');
    await shot(page, 'cloud-config');
    await dialog.getByTestId('cloud-config-save').click();
    await expect(panel(page)).not.toHaveAttribute('data-state', 'unconfigured');
  });
});
