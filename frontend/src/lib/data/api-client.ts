/**
 * The only module that talks to the local service. Failures always surface as one of
 * these errors, so no caller can mistake an unreachable service for an empty library.
 */
export class ServiceUnavailableError extends Error {
  constructor() {
    super('本地服务没有响应。');
    this.name = 'ServiceUnavailableError';
  }
}

export class ApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly status: number,
    readonly retryable: boolean,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

interface ErrorBody {
  error?: { code?: string; message?: string; retryable?: boolean };
}

let csrfToken: string | null = null;

async function send(path: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(path, { ...init, credentials: 'same-origin' });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ServiceUnavailableError();
  }
}

async function failure(response: Response): Promise<Error> {
  // A proxy or anything else answering without our envelope means the service is not there.
  const body = (await response.json().catch(() => null)) as ErrorBody | null;
  if (!body?.error?.code) return new ServiceUnavailableError();
  return new ApiError(
    body.error.code,
    body.error.message ?? '请求未能完成。',
    response.status,
    body.error.retryable ?? false,
  );
}

async function loadCsrfToken(signal?: AbortSignal): Promise<string> {
  const response = await send('/api/v1/session', { signal });
  if (!response.ok) throw await failure(response);
  const token = ((await response.json()) as { csrfToken: string }).csrfToken;
  csrfToken = token;
  return token;
}

export async function apiGet<T>(
  path: string,
  params?: URLSearchParams,
  signal?: AbortSignal,
): Promise<T> {
  const query = params?.size ? `?${params}` : '';
  const response = await send(`${path}${query}`, {
    signal,
    headers: { Accept: 'application/json' },
  });
  if (!response.ok) throw await failure(response);
  // A dev server's HTML fallback is not an API answer.
  if (!response.headers.get('content-type')?.includes('application/json'))
    throw new ServiceUnavailableError();
  return (await response.json()) as T;
}

export async function apiWrite<T>(method: 'PATCH' | 'POST', path: string, body?: unknown) {
  const attempt = async (token: string) =>
    send(path, {
      method,
      headers: { 'Content-Type': 'application/json', 'X-Atlas-CSRF': token },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  let response = await attempt(csrfToken ?? (await loadCsrfToken()));
  if (!response.ok) {
    const error = await failure(response);
    // The token changes when the service restarts; fetch it once and try again.
    if (!(error instanceof ApiError) || error.code !== 'csrf_invalid') throw error;
    response = await attempt(await loadCsrfToken());
    if (!response.ok) throw await failure(response);
  }
  return (await response.json()) as T;
}

export function resetApiSession() {
  csrfToken = null;
}
