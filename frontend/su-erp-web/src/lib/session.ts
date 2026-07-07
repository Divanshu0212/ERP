// Login/session flow shared by the login page and its tests.
//
// Keeps the token-storage + role-decode + redirect-target logic in one testable
// place so the page component stays thin.

import { api } from "@/lib/api";
import { setToken, decodeToken } from "@/lib/auth";
import { dashboardPathForRole } from "@/lib/routes";

/** Shape returned by the auth-service login endpoint (inside the envelope). */
export interface LoginResponse {
  access: string;
  refresh: string;
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
 * `institutionSlug` is required by the backend (users are scoped to a tenant
 * institution; there is no cross-tenant email lookup). Role/tenant come from
 * the verified JWT claims, since the login response carries only the token
 * pair, not a user object. Throws `ApiError` (from `api.post`) on failure —
 * callers surface `error.message` to the user.
 */
export async function login(
  institutionSlug: string,
  email: string,
  password: string,
): Promise<LoginResult> {
  const data = await api.post<LoginResponse>("/api/v1/auth/login", {
    institution_slug: institutionSlug,
    email,
    password,
  });

  setToken(data.access);

  const claims = decodeToken(data.access);

  return {
    role: claims.role,
    tenant: claims.tenant,
    redirectTo: dashboardPathForRole(claims.role),
  };
}

/** Shape returned by GET /api/v1/auth/me (inside the envelope). */
export interface MeResponse {
  user_code: string | null;
  email: string;
  role: string;
  tenant: string;
}

/** Fetch the caller's own identity record (real email, user_code) — used to
 * render the avatar/profile correctly instead of relying on the JWT `sub`
 * claim, which is a user_code, not an email. */
export async function fetchMe(): Promise<MeResponse> {
  return api.get<MeResponse>("/api/v1/auth/me");
}
