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

function buildUrl(path: string): string {
  return `${gatewayBaseUrl()}${path.startsWith("/") ? path : `/${path}`}`;
}

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

/** Fetch + parse the standard envelope, throwing ApiError on transport or envelope failure. */
async function unwrap<T>(
  fetchCall: () => Promise<Response>,
  method: string,
  path: string,
): Promise<T> {
  let response: Response;
  try {
    response = await fetchCall();
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

/**
 * Call the gateway and unwrap the response envelope.
 *
 * - `method`: HTTP method (GET, POST, ...).
 * - `path`: path beginning with "/" (e.g. "/api/v1/auth/login").
 * - `body`: optional JSON-serializable payload.
 */
export async function apiCall<T = unknown>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const url = buildUrl(path);
  const headers = authHeaders();
  const init: RequestInit = { method: method.toUpperCase(), headers };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }

  return unwrap<T>(() => fetch(url, init), method, path);
}

/**
 * Upload a file as multipart/form-data and unwrap the response envelope.
 * Distinct from apiCall: the body must NOT be JSON-serialized, and
 * Content-Type must be left unset so the browser sets the multipart
 * boundary itself.
 */
export async function apiUpload<T = unknown>(
  path: string,
  file: File,
  fieldName = "file",
): Promise<T> {
  const url = buildUrl(path);
  const headers = authHeaders();
  const formData = new FormData();
  formData.append(fieldName, file);

  return unwrap<T>(() => fetch(url, { method: "POST", headers, body: formData }), "POST", path);
}

/** Convenience wrappers around apiCall/apiUpload. */
export const api = {
  get: <T = unknown>(path: string) => apiCall<T>("GET", path),
  post: <T = unknown>(path: string, body?: unknown) => apiCall<T>("POST", path, body),
  put: <T = unknown>(path: string, body?: unknown) => apiCall<T>("PUT", path, body),
  patch: <T = unknown>(path: string, body?: unknown) => apiCall<T>("PATCH", path, body),
  delete: <T = unknown>(path: string) => apiCall<T>("DELETE", path),
  upload: <T = unknown>(path: string, file: File, fieldName?: string) =>
    apiUpload<T>(path, file, fieldName),
};
