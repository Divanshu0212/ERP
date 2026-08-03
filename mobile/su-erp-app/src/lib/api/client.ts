import type { ApiEnvelope, TokenPair } from '@api-types/index';

import { clearRefreshToken, readRefreshToken, saveRefreshToken } from '../auth/storage';
import { currentBaseUrl, invalidateBaseUrl, resolveBaseUrl } from './endpoint';

/**
 * The gateway origin, resolved at runtime — see ./endpoint.
 *
 * Was a build-time constant. It is a function now because the app has to
 * reach the same backend over a Cloudflare tunnel from the outside world and
 * over `adb reverse` on the dev machine, and a quick tunnel's hostname
 * changes on every restart. Callers that can await should prefer
 * `resolveBaseUrl()`; this is the synchronous best-known answer.
 */
export function baseUrl(): string {
  return currentBaseUrl();
}

/**
 * The access token is held here, in memory, for exactly this reason: it has a
 * 15-minute life and writing it to disk would widen the blast radius of a
 * compromised device for no benefit. Only the refresh token is persisted,
 * and only to SecureStore.
 */
let accessToken: string | null = null;
let onAuthFailure: (() => void) | null = null;
/** Concurrent 401s must not each fire their own refresh — they share this. */
let inFlightRefresh: Promise<TokenPair> | null = null;

/**
 * Reachability observers, registered by the connectivity layer.
 *
 * Injected rather than imported: the queue already imports this module, so
 * importing the connectivity store here would close a cycle
 * (client -> connectivity -> queue -> client).
 */
let onReachable: (() => void) | null = null;
let onUnreachable: (() => void) | null = null;

export function setReachabilityHandlers(handlers: {
  onReachable: () => void;
  onUnreachable: () => void;
}): void {
  onReachable = handlers.onReachable;
  onUnreachable = handlers.onUnreachable;
}

/**
 * How long a request may hang before it is treated as unreachable.
 *
 * NetInfo reporting "online" only means the radio is up. A phone with full
 * bars inside a hostel block can still have no route to the gateway, and
 * without a deadline `fetch` waits on that dead socket indefinitely: the
 * mutation never resolves, never rejects, and never reaches the offline
 * queue, so the warden is left believing the entry was saved.
 */
export const REQUEST_TIMEOUT_MS = 12_000;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly requestId: string | null = null,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/**
 * The server could not be reached at all — no response, as opposed to a
 * response that said no. Callers that can queue treat this exactly like being
 * offline, because for the user it is indistinguishable.
 */
export class NetworkError extends Error {
  constructor(message = 'Could not reach the server.') {
    super(message);
    this.name = 'NetworkError';
  }
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function setOnAuthFailure(handler: () => void): void {
  onAuthFailure = handler;
}

function requestId(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/**
 * ``fetch`` with a deadline. An aborted or failed connection surfaces as
 * NetworkError so it can be told apart from an HTTP error the server sent.
 */
async function fetchWithTimeout(url: string, init: RequestInit): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(url, { ...init, signal: controller.signal });
    // Any response at all — even a 4xx — proves the server is reachable, which
    // is the signal NetInfo cannot give us when the radio is up but the route
    // is dead.
    onReachable?.();
    return response;
  } catch (error) {
    onUnreachable?.();
    // The endpoint we picked is no longer answering. Forget it so the next
    // call re-probes: the tunnel may have restarted with a new hostname, or
    // the phone may have been unplugged from `adb reverse`.
    invalidateBaseUrl();
    if ((error as Error)?.name === 'AbortError') {
      throw new NetworkError('The server took too long to respond.');
    }
    throw new NetworkError();
  } finally {
    clearTimeout(timer);
  }
}

async function refreshTokenPair(): Promise<TokenPair> {
  const refresh = await readRefreshToken();
  if (!refresh) throw new ApiError('No refresh token.', 401);

  const response = await fetchWithTimeout(`${await resolveBaseUrl()}/api/v1/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Request-Id': requestId() },
    body: JSON.stringify({ refresh }),
  });

  if (!response.ok) throw new ApiError('Refresh rejected.', response.status);

  const body = (await response.json()) as ApiEnvelope<TokenPair>;
  if (!body.data) throw new ApiError('Refresh returned no tokens.', 401);

  setAccessToken(body.data.access);
  await saveRefreshToken(body.data.refresh);
  return body.data;
}

/** Deduplicates concurrent refreshes so one 401 storm makes one round-trip. */
function refreshOnce(): Promise<TokenPair> {
  if (!inFlightRefresh) {
    inFlightRefresh = refreshTokenPair().finally(() => {
      inFlightRefresh = null;
    });
  }
  return inFlightRefresh;
}

async function endSession(): Promise<void> {
  setAccessToken(null);
  await clearRefreshToken();
  onAuthFailure?.();
}

export interface RequestOptions extends RequestInit {
  /** Sent as Idempotency-Key so a replayed queued mutation is a no-op. */
  idempotencyKey?: string;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { idempotencyKey, ...init } = options;

  const send = async (): Promise<Response> => {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'X-Request-Id': requestId(),
      ...((init.headers as Record<string, string>) ?? {}),
    };
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
    if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey;

    return fetchWithTimeout(`${await resolveBaseUrl()}${path}`, { ...init, headers });
  };

  let response = await send();

  if (response.status === 401) {
    try {
      await refreshOnce();
    } catch {
      await endSession();
      throw new ApiError('Session expired.', 401);
    }
    response = await send();
    if (response.status === 401) {
      await endSession();
      throw new ApiError('Session expired.', 401);
    }
  }

  const body = (await response.json()) as ApiEnvelope<T>;

  if (!response.ok || !body.success) {
    throw new ApiError(
      body?.message || `Request failed (${response.status})`,
      response.status,
      response.headers?.get?.('X-Request-Id') ?? null,
    );
  }

  return body.data as T;
}

export { refreshOnce as refreshSession };
