import { expect, test, type Page } from '@playwright/test';
import { access, mkdir, readdir, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { noHorizontalScroll, viewportTag } from './evidence';
import { enterRealMode, RealService } from './real-service';

/**
 * Real right clicks on the real page, against the real API and real folders. The test library's
 * shell stands in for the desktop and Recycle Bin, and nothing here starts a program.
 */
const evidenceDir = resolve('../artifacts/library-menu');
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

interface Work {
  id: string;
  title: string;
}

let next = 0;
async function freshWork(kind = 'game'): Promise<Work> {
  const listed = await (
    await call(`/works?limit=100&platform=dlsite&kind=${kind}&search=${encodeURIComponent('')}`)
  ).json();
  const work = listed.items[next++ % listed.items.length] as Work;
  const linked = await (await call(`/works/${work.id}/local-copies`)).json();
  for (const copy of linked.copies) await call(`/local-copies/${copy.id}`, 'DELETE');
  return work;
}

async function linkFolder(work: Work) {
  const folder = join(place, `${test.info().project.name}-${next}-${work.id}`);
  await mkdir(folder, { recursive: true });
  await writeFile(join(folder, 'Game.exe'), 'not run');
  await call(`/works/${work.id}/local-copies`, 'POST', { root: folder, entry: 'Game.exe' });
  return folder;
}

/** Finds it by its own name, so the card under the mouse is really this work. */
async function openMenu(page: Page, work: Work) {
  await page.goto(`${service.origin}/library?q=${encodeURIComponent(work.title)}`);
  const card = page.locator(`[data-game-id="${work.id}"]`);
  await card.waitFor();
  await card.click({ button: 'right' });
  const menu = page.getByTestId('work-menu');
  await expect(menu).toBeVisible();
  return menu;
}

test.describe('right click on a work', () => {
  test.beforeAll(async () => {
    test.skip(!coreProjects.includes(test.info().project.name), 'core tiers only');
    test.setTimeout(120_000);
    service = await RealService.create(120, 8812);
    await service.start();
    place = join(service.dataDir, '..', '作品 置き場');
    await mkdir(place, { recursive: true });
    token = (await (await fetch(`${service.origin}/api/v1/session`)).json()).csrfToken;
  });
  test.afterAll(async () => service?.dispose());
  test.beforeEach(async ({ page }) => {
    await enterRealMode(page);
  });

  test('without local files it offers to install, and that opens the install flow', async ({
    page,
  }) => {
    const work = await freshWork();
    const menu = await openMenu(page, work);
    await expect(menu.getByTestId('menu-install')).toBeVisible();
    await expect(menu.getByTestId('menu-play')).toHaveCount(0);
    await shot(page, 'menu-install');
    await menu.getByTestId('menu-manage').hover();
    const manage = menu.getByTestId('menu-manage-list');
    await expect(manage.getByRole('menuitem')).toHaveCount(3);
    await expect(manage.getByRole('menuitem', { name: '卸载' })).toBeDisabled();
    await menu.getByTestId('menu-install').click();
    await expect(page).toHaveURL(new RegExp(`/library/${work.id}$`));
    // The install really started: this library has no platform session, and it says so. The
    // address is tidied, so going back and forward does not start it again.
    await expect(page.getByRole('alert').filter({ hasText: '请先登录' })).toBeVisible({
      timeout: 15_000,
    });
  });

  test('with local files it starts the game, and manages exactly three things', async ({
    page,
  }) => {
    const work = await freshWork();
    await linkFolder(work);
    const menu = await openMenu(page, work);
    await expect(menu.getByTestId('menu-play')).toHaveText('开始游戏');
    await expect(menu.getByTestId('menu-install')).toHaveCount(0);
    await menu.getByTestId('menu-manage').hover();
    const manage = menu.getByTestId('menu-manage-list');
    await expect(manage.getByRole('menuitem')).toHaveText([
      '添加桌面快捷方式',
      '浏览本地文件',
      '卸载',
    ]);
    await shot(page, 'menu-manage');
    await noHorizontalScroll(page);
    const box = (await manage.boundingBox())!;
    const size = page.viewportSize()!;
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(size.width);

    await manage.getByRole('menuitem', { name: '添加桌面快捷方式' }).click();
    await expect(menu).toHaveCount(0);
    await expect
      .poll(async () =>
        (await readdir(join(service.dataDir, 'fake-desktop')).catch(() => [])).some((name) =>
          name.endsWith('.lnk'),
        ),
      )
      .toBe(true);
  });

  test('uninstalling says which folder, moves it, and the menu goes back to install', async ({
    page,
  }) => {
    const work = await freshWork();
    const folder = await linkFolder(work);
    const menu = await openMenu(page, work);
    await menu.getByTestId('menu-manage').hover();
    await menu.getByTestId('menu-uninstall').click();
    const dialog = page.getByTestId('uninstall-dialog');
    await expect(dialog.getByTestId('uninstall-root')).toContainText(folder.split(/[\\/]/).pop()!);
    await expect(dialog.getByTestId('uninstall-size')).toContainText('1 个文件');
    await shot(page, 'uninstall-dialog');
    // Nothing goes on a cancel.
    await dialog.getByRole('button', { name: '取消' }).click();
    await expect(dialog).toHaveCount(0);
    await access(join(folder, 'Game.exe'));

    const again = await openMenu(page, work);
    await again.getByTestId('menu-manage').hover();
    await again.getByTestId('menu-uninstall').click();
    await page.getByTestId('uninstall-confirm').click();
    await expect(page.getByTestId('uninstall-dialog')).toHaveCount(0);
    await expect(access(folder)).rejects.toThrow();
    const after = await openMenu(page, work);
    await expect(after.getByTestId('menu-install')).toBeVisible();
  });

  test('the detail page can uninstall too, and a shared folder is refused', async ({ page }) => {
    const work = await freshWork();
    const folder = await linkFolder(work);
    await page.goto(`${service.origin}/library/${work.id}`);
    await page.getByTestId('copy-uninstall').click();
    await page.getByTestId('uninstall-confirm').click();
    await expect(page.getByTestId('uninstall-dialog')).toHaveCount(0);
    await expect(access(folder)).rejects.toThrow();
    await expect(page.getByTestId('copy-uninstall')).toHaveCount(0);

    const one = await freshWork();
    const two = await freshWork();
    const outer = join(place, `${test.info().project.name}-outer-${next}`);
    await mkdir(join(outer, 'inner'), { recursive: true });
    await call(`/works/${one.id}/local-copies`, 'POST', { root: outer });
    await call(`/works/${two.id}/local-copies`, 'POST', { root: join(outer, 'inner') });
    await page.goto(`${service.origin}/library/${one.id}`);
    await page.getByTestId('copy-uninstall').click();
    await expect(page.getByTestId('uninstall-problem')).toContainText('重叠');
    await expect(page.getByTestId('uninstall-confirm')).toBeDisabled();
    await shot(page, 'uninstall-refused');
    await access(join(outer, 'inner'));
  });

  test('favorites and named collections, from the menu to their own page', async ({ page }) => {
    const work = await freshWork();
    const menu = await openMenu(page, work);
    await menu.getByTestId('menu-favorite').click();
    await expect(page.locator(`[data-game-id="${work.id}"] [aria-pressed="true"]`)).toBeVisible();

    const name = `赛博坐牢 ${test.info().project.name}`;
    const second = await openMenu(page, work);
    await expect(second.getByTestId('menu-favorite')).toHaveText('从收藏夹移除');
    await second.getByTestId('menu-add').hover();
    await second.getByTestId('menu-new-collection').click();
    await page.getByLabel('收藏名称').fill(name);
    await page.getByRole('button', { name: '创建' }).click();
    await expect(page.getByLabel('收藏名称')).toHaveCount(0);

    const third = await openMenu(page, work);
    await third.getByTestId('menu-add').hover();
    const item = third.getByTestId('menu-add-list').getByRole('menuitemcheckbox', { name });
    await expect(item).toHaveAttribute('aria-checked', 'true');
    await shot(page, 'menu-add');
    await page.keyboard.press('Escape');
    await page.keyboard.press('Escape');
    await expect(third).toHaveCount(0);

    await page.getByRole('link', { name: '收藏夹' }).first().click();
    const list = page.getByTestId('collections-list');
    await expect(list).toContainText(name);
    await shot(page, 'collections-page');
    await noHorizontalScroll(page);
    await list.getByRole('link', { name: new RegExp(name) }).click();
    await expect(page.getByTestId('library-results')).toHaveAttribute('data-count', '1');
    await expect(page.locator(`[data-game-id="${work.id}"]`)).toBeVisible();
    await expect(page.getByTestId('library-collection')).toContainText(name);

    await page.getByRole('link', { name: '收藏夹' }).first().click();
    await page.getByRole('button', { name: `删除 ${name}` }).click();
    await page.getByTestId('collection-remove-confirm').click();
    await expect(list).not.toContainText(name);
    expect((await (await call(`/works/${work.id}`)).json()).id).toBe(work.id);
  });

  test('several programs: start asks which one, once; no download offer once it is here', async ({
    page,
  }) => {
    const work = await freshWork();
    const folder = join(place, `${test.info().project.name}-many-${next}`);
    await mkdir(folder, { recursive: true });
    await writeFile(join(folder, 'Game.exe'), 'not run');
    await writeFile(join(folder, 'Setup.exe'), 'not run');
    await call(`/works/${work.id}/local-copies`, 'POST', { root: folder });
    const menu = await openMenu(page, work);
    await menu.getByTestId('menu-play').click();
    const chooser = page.getByTestId('choose-program');
    await expect(chooser.getByRole('button')).toHaveCount(2);
    await expect(page).toHaveURL(new RegExp(`/library/${work.id}$`));
    await shot(page, 'choose-program');
    await expect(page.getByTestId('download-action')).toHaveCount(0);
    await expect(page.getByTestId('launch')).toBeEnabled();
    // Choosing is remembered. It is read back rather than clicked through, so nothing is started.
    await call(
      `/local-copies/${(await (await call(`/works/${work.id}/local-copies`)).json()).copies[0].id}`,
      'PATCH',
      { entry: 'Game.exe' },
    );
    const after = await openMenu(page, work);
    await expect(after.getByTestId('menu-play')).not.toHaveAttribute('title', /.+/);
  });

  test('the keyboard can drive it, and an ordinary left click still opens the work', async ({
    page,
  }) => {
    const work = await freshWork();
    const menu = await openMenu(page, work);
    await expect(menu.getByRole('menuitem').first()).toBeFocused();
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('ArrowDown');
    await expect(menu.getByTestId('menu-add')).toBeFocused();
    await page.keyboard.press('ArrowRight');
    await expect(menu.getByTestId('menu-new-collection')).toBeFocused();
    await page.keyboard.press('ArrowLeft');
    await expect(menu.getByTestId('menu-add-list')).toHaveCount(0);
    await page.keyboard.press('Escape');
    await expect(menu).toHaveCount(0);
    await page.locator(`[data-game-id="${work.id}"] .game-link`).click();
    await expect(page).toHaveURL(new RegExp(`/library/${work.id}$`));
  });
});
