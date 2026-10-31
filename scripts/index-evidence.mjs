// Builds artifacts/phase-1-acceptance/INDEX.md from the files the Playwright run wrote.
// Usage (from the repository root, after `npm run test:e2e` in frontend): node scripts/index-evidence.mjs
import { existsSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)), 'artifacts', 'phase-1-acceptance');
const tiers = ['1080p', '2k', '4k', '4k-150', '4k-200', 'narrow', 'laptop'];
const shotsDir = join(root, 'screenshots');
if (!existsSync(shotsDir)) throw new Error(`No screenshots under ${shotsDir}; run the e2e suite first.`);

/** name -> tier -> file */
const shots = new Map();
const viewports = {};
for (const tier of tiers) {
  const dir = join(shotsDir, tier);
  if (!existsSync(dir)) continue;
  for (const file of readdirSync(dir).filter((entry) => entry.endsWith('.png'))) {
    const [name, viewport] = file.replace(/\.png$/, '').split('__');
    viewports[tier] = viewport;
    if (!shots.has(name)) shots.set(name, {});
    shots.get(name)[tier] = `screenshots/${tier}/${file}`;
  }
}

const lines = [
  '# Phase 1 验收证据索引',
  '',
  `生成时间：${new Date().toISOString()}。由 \`node scripts/index-evidence.mjs\` 根据本次 Playwright 运行生成。`,
  '',
  '## 截图覆盖（页面-状态 × CSS 视口@DPR）',
  '',
  `| 截图 | ${tiers.map((tier) => `${tier}<br>${viewports[tier] ?? '—'}`).join(' | ')} | 档数 |`,
  `|---|${tiers.map(() => ':-:').join('|')}|:-:|`,
];
for (const name of [...shots.keys()].sort()) {
  const row = shots.get(name);
  const cells = tiers.map((tier) => (row[tier] ? `[✓](${row[tier]})` : '—'));
  lines.push(`| ${name} | ${cells.join(' | ')} | ${Object.keys(row).length} |`);
}
const total = [...shots.values()].reduce((sum, row) => sum + Object.keys(row).length, 0);
lines.push('', `共 ${shots.size} 种页面/状态，${total} 张截图。`, '');

const layoutFile = join(root, 'layout-checks.jsonl');
if (existsSync(layoutFile)) {
  lines.push('## 已通过的布局检查', '', '| 检查组 | 档位 | 视口 | 断言 |', '|---|---|---|---|');
  const rows = readFileSync(layoutFile, 'utf8').trim().split('\n').map((line) => JSON.parse(line));
  rows.sort((a, b) => a.name.localeCompare(b.name) || tiers.indexOf(a.project) - tiers.indexOf(b.project));
  for (const row of rows)
    lines.push(`| ${row.name} | ${row.project} | ${row.viewport} | ${row.checks.join('；')} |`);
  lines.push('');
}

const perfDir = join(root, 'performance');
if (existsSync(perfDir)) {
  lines.push('## 性能与离线样本', '');
  for (const file of readdirSync(perfDir).sort()) lines.push(`- [${file}](performance/${file})`);
  lines.push('');
}

writeFileSync(join(root, 'INDEX.md'), lines.join('\n'));
console.log(`INDEX.md: ${shots.size} states, ${total} screenshots`);
