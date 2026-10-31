import { expect, test, type Page } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { noHorizontalScroll, viewportTag } from './evidence';
import { enterRealMode, RealService } from './real-service';

/**
 * Finding saves through the real page and API, with real files in a made-up user folder. The test
 * library has no way to see the real AppData or registry, and nothing here starts a program.
 */
const evidenceDir = resolve('../artifacts/save-discovery');
const coreProjects = ['1080p', 'narrow', '4k-200'];

let service: RealService;
let token: string;

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

let next = 0;
async function game(setup?: (folder: string) => Promise<void>) {
  next += 1;
  const listed = await (await call('/works?limit=100&platform=dlsite&kind=game')).json();
  const work = listed.items[next % listed.items.length];
  const linked = await (await call(`/works/${work.id}/local-copies`)).json();
  for (const copy of linked.copies) await call(`/local-copies/${copy.id}`, 'DELETE');
  await call(`/works/${work.id}/save-config`, 'PUT', { rules: [], confirmedNone: false });
  const folder = join(service.dataDir, '..', `合成游戏 ${test.info().project.name} ${next}`);
  await mkdir(folder, { recursive: true });
  await writeFile(join(folder, 'Game.exe'), 'not run');
  await setup?.(folder);
  await call(`/works/${work.id}/local-copies`, 'POST', { root: folder, entry: 'Game.exe' });
  return { id: work.id as string, folder };
}

async function open(page: Page, id: string) {
  await page.goto(`${service.origin}/library/${id}`);
  // Finding saves does not need Google: it is there before any connection.
  await page.getByTestId('cloud-configure-again').click();
  return page.getByTestId('save-finder');
}

const rulesOf = async (id: string) =>
  (await (await call(`/works/${id}/save-config`)).json()).rules as { kind: string; path: string }[];

test.describe('finding saves', () => {
  test.beforeAll(async () => {
    test.skip(!coreProjects.includes(test.info().project.name), 'core tiers only');
    test.setTimeout(120_000);
    service = await RealService.create(60, 8815);
    await service.start();
    token = (await (await fetch(`${service.origin}/api/v1/session`)).json()).csrfToken;
  });
  test.afterAll(async () => service?.dispose());
  test.beforeEach(async ({ page }) => {
    await enterRealMode(page);
  });

  test('a Unity game: the place follows from its own files, and is used only once ticked', async ({
    page,
  }) => {
    const company = `合成社团${next}`;
    const { id } = await game(async (folder) => {
      await mkdir(join(folder, 'Game_Data'));
      await writeFile(join(folder, 'Game_Data', 'app.info'), `${company}\n合成冒险\n`);
    });
    const place = join(service.dataDir, 'fake-home', 'AppData', 'LocalLow', company, '合成冒险');
    await mkdir(place, { recursive: true });
    await writeFile(join(place, 'slot1.dat'), 'made up');
    const finder = await open(page, id);
    await expect(finder.getByTestId('save-engine')).toContainText('Unity');
    const likely = finder.getByTestId('save-likely');
    await expect(likely).toContainText('合成冒险');
    await expect(likely).toContainText('slot1.dat');
    await shot(page, 'finder-unity');
    await noHorizontalScroll(page);
    // Found is not chosen.
    expect(await rulesOf(id)).toEqual([]);
    await likely.getByRole('checkbox').check();
    await page.getByTestId('cloud-config-save').click();
    await expect.poll(() => rulesOf(id)).toEqual([{ kind: 'outside', path: place }]);
  });

  test('playing once shows where it wrote, with the likely apart from the noise', async ({
    page,
  }) => {
    const { id, folder } = await game();
    const finder = await open(page, id);
    await expect(finder.getByTestId('save-none')).toBeVisible();
    await shot(page, 'finder-empty');
    await finder.getByTestId('save-start').click();
    await expect(finder.getByTestId('save-recording')).toBeVisible();
    await shot(page, 'finder-recording');

    const home = join(service.dataDir, 'fake-home', 'AppData');
    const unique = `${test.info().project.name}${next}`;
    await mkdir(join(folder, 'userdata'), { recursive: true });
    await writeFile(join(folder, 'userdata', 'slot1.sav'), 'made up');
    await writeFile(join(folder, 'Save03.rvdata2'), 'made up');
    await writeFile(join(folder, 'output.log'), 'noise');
    const other = join(home, 'Local', `NotesApp${unique}`, 'state');
    await mkdir(other, { recursive: true });
    await writeFile(join(other, 'window.json'), 'noise');
    const browser = join(home, 'Local', 'Google', 'Chrome');
    await mkdir(browser, { recursive: true });
    await writeFile(join(browser, 'History'), 'noise');

    await finder.getByTestId('save-finish').click();
    const likely = finder.getByTestId('save-likely');
    await expect(likely).toContainText('userdata', { timeout: 20_000 });
    await expect(likely).toContainText('Save*.rvdata2');
    await expect(finder).not.toContainText('output.log');
    await expect(finder).not.toContainText('Chrome');
    await expect(likely).not.toContainText('NotesApp');
    await finder.getByTestId('save-others-toggle').click();
    await expect(finder.getByTestId('save-others')).toContainText(`NotesApp${unique}`);
    await shot(page, 'finder-after-play');
    await noHorizontalScroll(page);

    await likely.getByRole('checkbox', { name: /Save\*\.rvdata2/ }).check();
    await page.getByTestId('cloud-config-save').click();
    await expect.poll(() => rulesOf(id)).toEqual([{ kind: 'inside', path: 'Save*.rvdata2' }]);
  });

  test('a location can be typed by hand too, including a registry key, and a bad one is refused', async ({
    page,
  }) => {
    const { id } = await game();
    await open(page, id);
    const dialog = page.getByTestId('cloud-config');
    await dialog.getByLabel('存档位置类型').selectOption('registry');
    await dialog.getByLabel('存档路径').fill('HKCU\\Software\\Microsoft\\Windows');
    await page.getByTestId('cloud-config-save').click();
    await expect(dialog.getByRole('alert')).toBeVisible();
    expect(await rulesOf(id)).toEqual([]);
    await dialog.getByLabel('存档路径').fill('HKCU\\Software\\合成社团\\合成冒险');
    await page.getByTestId('cloud-config-save').click();
    await expect
      .poll(() => rulesOf(id))
      .toEqual([{ kind: 'registry', path: 'HKCU\\Software\\合成社团\\合成冒险' }]);
  });
});
