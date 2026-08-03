/** Mirrors accounts.models.User.Role. */
export type Role =
  | 'student'
  | 'faculty'
  | 'warden'
  | 'driver'
  | 'admin'
  | 'alumni'
  | 'superadmin'
  | 'canteen_owner';

export interface LoginRequest {
  institution_slug: string;
  email: string;
  password: string;
  /** Mobile only. Omitting these keeps the stateless web login path. */
  device_id?: string;
  platform?: string;
  model_name?: string;
  push_token?: string;
}

export interface TokenPair {
  access: string;
  refresh: string;
}

export interface MeResponse {
  user_code: string;
  email: string;
  role: Role;
  tenant: string;
}

export interface DeviceSummary {
  device_id: string;
  platform: string;
  model_name: string;
  last_seen_at: string;
  is_stale: boolean;
}

/** Claims carried by every access token. */
export interface JwtClaims {
  sub: string;
  role: Role;
  tenant: string;
  exp: number;
}
