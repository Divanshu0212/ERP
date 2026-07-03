// Login/session flow shared by the login page and its tests.
//
// Keeps the token-storage + role-decode + redirect-target logic in one testable
// place so the page component stays thin.

import { api } from "@/lib/api";
import { setToken, decodeToken } from "@/lib/auth";
import { dashboardPathForRole } from "@/lib/routes";

/** Shape returned by the auth-service login endpoint (inside the envelope). */
export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  user: {
    id: string;
    email: string;
    role: string;
    tenant_id: string;
  };
}

/** Result of a successful login: the stored role/tenant and where to redirect. */
export interface LoginResult {
  role: string;
  tenant: string;
  redirectTo: string;
}

/**
 * Perform login against the gateway, persist the access token, and compute the
 * role-specific dashboard path.
 *
 * Prefers the role/tenant decoded from the JWT (authoritative for the token);
 * falls back to the user object in the response body. Throws `ApiError` (from
 * `api.post`) on failure — callers surface `error.message` to the user.
 */
export async function login(email: string, password: string): Promise<LoginResult> {
  const data = await api.post<LoginResponse>("/api/v1/auth/login", { email, password });

  setToken(data.access_token);

  let role = data.user?.role;
  let tenant = data.user?.tenant_id;
  try {
    const claims = decodeToken(data.access_token);
    role = claims.role ?? role;
    tenant = claims.tenant ?? tenant;
  } catch {
    // Malformed token: fall back to the user object from the response body.
  }

  return {
    role,
    tenant,
    redirectTo: dashboardPathForRole(role),
  };
}
