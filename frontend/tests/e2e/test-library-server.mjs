import { execFileSync, spawn } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import process from 'node:process';

// A real service on a new temporary database, serving the production build. LOCALAPPDATA points
// into the same folder, so nothing here can reach a real library.
const backend = resolve('../backend');
const python = resolve(backend, '.venv/Scripts/python.exe');
const temp = mkdtempSync(join(tmpdir(), 'atlas e2e 页面测试-'));
const data = join(temp, 'library');
const env = {
  ...process.env,
  LOCALAPPDATA: join(temp, 'localappdata'),
  PYTHONIOENCODING: 'utf-8',
  ATLAS_DEV_ORIGINS: '',
};
execFileSync(python, ['-m', 'app', 'seed-test', '--data-dir', data, '--size', '1500'], {
  cwd: backend,
  env,
  stdio: 'ignore',
});
const service = spawn(
  python,
  ['-m', 'app', 'serve', '--profile', 'test', '--data-dir', data, '--port', '4173'],
  { cwd: backend, env, stdio: 'inherit' },
);
const finish = (code) => {
  service.kill();
  rmSync(temp, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  process.exit(code);
};
service.on('exit', (code) => finish(code ?? 0));
process.on('SIGINT', () => finish(0));
process.on('SIGTERM', () => finish(0));
