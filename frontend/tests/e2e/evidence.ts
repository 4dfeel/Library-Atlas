import { expect, type Page, type TestInfo } from '@playwright/test';
import { appendFile, mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

/** Phase 1 acceptance evidence; git-ignored, indexed by scripts/index-evidence.mjs. */
export const evidenceRoot = resolve('../artifacts/phase-1-acceptance');
export const appOrigin = 'http://127.0.0.1:4173';

/** e.g. "1920x1080@2x": the CSS viewport and DPR the screenshot was taken at. */
export function viewportTag(page: Page, info: TestInfo) {
  const viewport = page.viewportSize()!;
  const dpr = info.project.use.deviceScaleFactor ?? 1;
  return `${viewport.width}x${viewport.height}@${dpr}x`;
}

/** Saves `<page>-<state>__<viewport>@<dpr>.png` under the project tier. */
export async function screenshot(page: Page, info: TestInfo, name: string) {
  const dir = resolve(evidenceRoot, 'screenshots', info.project.name);
  await mkdir(dir, { recursive: true });
  const path = resolve(dir, `${name}__${viewportTag(page, info)}.png`);
  await page.screenshot({ path, animations: 'disabled' });
  await info.attach(name, { path, contentType: 'image/png' });
}

/** Records a layout check that already passed its assertions. */
export async function recordLayout(page: Page, info: TestInfo, name: string, checks: string[]) {
  await mkdir(evidenceRoot, { recursive: true });
  const row = { project: info.project.name, viewport: viewportTag(page, info), name, checks };
  await appendFile(resolve(evidenceRoot, 'layout-checks.jsonl'), `${JSON.stringify(row)}\n`);
}

export async function writeEvidence(info: TestInfo, name: string, data: unknown) {
  const dir = resolve(evidenceRoot, 'performance');
  await mkdir(dir, { recursive: true });
  const path = resolve(dir, name);
  await writeFile(path, JSON.stringify(data, null, 2));
  await info.attach(name, { path, contentType: 'application/json' });
}

export async function noHorizontalScroll(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);
}

/** Collects every request that leaves the local preview server. */
export function trackExternal(page: Page) {
  const external: string[] = [];
  page.on('request', (request) => {
    if (/^https?:/.test(request.url()) && !request.url().startsWith(`${appOrigin}/`))
      external.push(request.url());
  });
  return external;
}

/** Fails on console errors and unhandled rejections; call `assert` at the end. */
export function watchConsole(page: Page, allowed: RegExp[] = []) {
  const problems: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error' && !allowed.some((pattern) => pattern.test(message.text())))
      problems.push(message.text());
  });
  page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`));
  return { assert: () => expect(problems).toEqual([]) };
}

export async function noPrivateData(page: Page) {
  await expect(page.locator('body')).not.toContainText('PRIVATE_SENTINEL');
  expect(await page.locator('body').ariaSnapshot()).not.toContain('PRIVATE_SENTINEL');
}
