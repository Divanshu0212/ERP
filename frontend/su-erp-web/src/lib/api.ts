// Gateway API client for SU-ERP.
//
// Every backend service is reached through the gateway. This client attaches
// the bearer token, sends/parses JSON, and unwraps the standard response
// envelope: { success, data, message, errors }.

import { getToken } from "@/lib/auth";

const DEFAULT_GATEWAY_URL = "http://localhost:8080";

/** Standard response envelope returned by all gateway-fronted services. */
export interface ApiEnvelope<T = unknown> {
  success: boolean;
  data: T;
  message: string;
  errors: unknown;
}

/** Error thrown when the envelope reports failure or a transport error occurs. */
export class ApiError extends Error {
  readonly status: number | null;
  readonly errors: unknown;

  constructor(message: string, status: number | null = null, errors: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.errors = errors;
  }
}

/** Gateway base URL from env, without a trailing slash. */
function gatewayBaseUrl(): string {
  const url = process.env.NEXT_PUBLIC_GATEWAY_URL || DEFAULT_GATEWAY_URL;
  return url.replace(/\/+$/, "");
}

/**
 * Call the gateway and unwrap the response envelope.
 *
 * - `method`: HTTP method (GET, POST, ...).
 * - `path`: path beginning with "/" (e.g. "/api/v1/auth/login").
 * - `body`: optional JSON-serializable payload.
 *
 * Returns `envelope.data` when `success === true`.
 * Throws `ApiError` when `success === false` (using `message`) or on a
 * network/parse failure.
 */
export async function apiCall<T = unknown>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const url = `${gatewayBaseUrl()}${path.startsWith("/") ? path : `/${path}`}`;

  const headers: Record<string, string> = { Accept: "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const init: RequestInit = { method: method.toUpperCase(), headers };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }

  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (cause) {
    const detail = cause instanceof Error ? cause.message : String(cause);
    throw new ApiError(`Network error calling ${method} ${path}: ${detail}`);
  }

  let envelope: ApiEnvelope<T>;
  try {
    envelope = (await response.json()) as ApiEnvelope<T>;
  } catch {
    throw new ApiError(
      `Invalid response from ${method} ${path} (status ${response.status})`,
      response.status,
    );
  }

  if (!envelope || envelope.success !== true) {
    const message = envelope?.message || `Request failed with status ${response.status}`;
    throw new ApiError(message, response.status, envelope?.errors ?? null);
  }

  return envelope.data;
}

/** Convenience wrappers around apiCall. */
export const api = {
  get: <T = unknown>(path: string) => apiCall<T>("GET", path),
  post: <T = unknown>(path: string, body?: unknown) => apiCall<T>("POST", path, body),
  put: <T = unknown>(path: string, body?: unknown) => apiCall<T>("PUT", path, body),
  patch: <T = unknown>(path: string, body?: unknown) => apiCall<T>("PATCH", path, body),
  delete: <T = unknown>(path: string) => apiCall<T>("DELETE", path),
};
