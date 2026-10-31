import { execFile, spawn, type ChildProcess } from 'node:child_process';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { promisify } from 'node:util';
import type { Page } from '@playwright/test';
import { appOrigin } from './evidence';

const run = promisify(execFile);
const backendDir = resolve('../backend');
const python = resolve(backendDir, '.venv/Scripts/python.exe');

/**
 * A real service process on an isolated temporary database, serving the production
 * build. Restarting it is a real restart; nothing here touches the normal data folder.
 */
export class RealService {
  private process: ChildProcess | null = null;
  private constructor(
    readonly dataDir: string,
    readonly port: number,
    private readonly profile: 'test' | 'real',
    private readonly tempRoot: string,
  ) {}

  get origin() {
    return `http://127.0.0.1:${this.port}`;
  }

  /** `size` ordinary synthetic works, or `null` for a new, empty real-profile library. */
  static async create(size: number | null, port: number): Promise<RealService> {
    const tempRoot = await mkdtemp(join(tmpdir(), 'atlas e2e 测试-'));
    const dataDir = join(tempRoot, 'library');
    if (size === null) {
      await run(python, ['-m', 'app', 'init', '--profile', 'real', '--data-dir', dataDir], {
        cwd: backendDir,
        env: serviceEnv(tempRoot),
      });
    } else {
      await run(python, ['-m', 'app', 'seed-test', '--data-dir', dataDir, '--size', String(size)], {
        cwd: backendDir,
        env: serviceEnv(tempRoot),
        timeout: 120_000,
      });
    }
    return new RealService(dataDir, port, size === null ? 'real' : 'test', tempRoot);
  }

  async start(): Promise<void> {
    this.process = spawn(
      python,
      [
        '-m',
        'app',
        'serve',
        '--profile',
        this.profile,
        '--data-dir',
        this.dataDir,
        '--port',
        String(this.port),
      ],
      { cwd: backendDir, env: serviceEnv(this.tempRoot), stdio: 'ignore' },
    );
    for (let attempt = 0; attempt < 100; attempt++) {
      try {
        if ((await fetch(`${this.origin}/api/v1/ready`)).ok) return;
      } catch {
        // Not listening yet.
      }
      await new Promise((done) => setTimeout(done, 100));
    }
    throw new Error('service did not become ready');
  }

  async stop(): Promise<void> {
    const child = this.process;
    this.process = null;
    if (!child || child.exitCode !== null) return;
    await new Promise<void>((done) => {
      child.once('exit', () => done());
      child.kill();
    });
  }

  async restart() {
    await this.stop();
    await this.start();
  }

  async dispose() {
    await this.stop();
    await rm(this.tempRoot, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  }
}

function serviceEnv(tempRoot: string): NodeJS.ProcessEnv {
  // LOCALAPPDATA points into the temp folder, so a mistake could not reach real data.
  return {
    ...process.env,
    LOCALAPPDATA: join(tempRoot, 'localappdata'),
    PYTHONIOENCODING: 'utf-8',
    ATLAS_DEV_ORIGINS: '',
  };
}

/** A work's personal fields as a test wants them, through the same address the page uses. */
export async function setPersonal(
  page: Page,
  id: string,
  fields: { status?: string; rating?: number | null; note?: string; favorite?: boolean },
) {
  const origin = new URL(page.url() === 'about:blank' ? appOrigin : page.url()).origin;
  const session = await (await page.request.get(`${origin}/api/v1/session`)).json();
  const work = await (await page.request.get(`${origin}/api/v1/works/${id}`)).json();
  const response = await page.request.patch(`${origin}/api/v1/works/${id}/personal`, {
    headers: { Origin: origin, 'X-Atlas-CSRF': session.csrfToken },
    data: { ...fields, expectedVersion: work.version },
  });
  if (!response.ok()) throw new Error(`could not set up ${id}: ${response.status()}`);
}

/** A work with nothing recorded on it, whatever an earlier test or viewport did. */
export const clearPersonal = (page: Page, id: string) =>
  setPersonal(page, id, { status: 'unplayed', rating: null, note: '', favorite: false });
