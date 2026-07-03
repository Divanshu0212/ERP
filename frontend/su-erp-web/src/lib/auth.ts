// Client-side JWT/session helpers for SU-ERP.
//
// Tokens are stored in localStorage. The access token is used for the
// Authorization header on gateway calls. Claims (role, tenant, sub) are
// decoded client-side ONLY for routing/UX. The gateway and services perform
// real signature verification (zero-trust); nothing here is a security
// boundary.

const ACCESS_TOKEN_KEY = "access_token";

/** JWT claims we rely on for routing. Extra claims are passed through. */
export interface TokenClaims {
  sub: string;
  role: string;
  tenant: string;
  [key: string]: unknown;
}

/** True when running in a browser with localStorage available. */
function hasStorage(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

/** Read the access token from localStorage. Returns null on the server or when unset. */
export function getToken(): string | null {
  if (!hasStorage()) return null;
  return window.localStorage.getItem(ACCESS_TOKEN_KEY);
}

/** Persist the access token to localStorage. No-op on the server. */
export function setToken(token: string): void {
  if (!hasStorage()) return;
  window.localStorage.setItem(ACCESS_TOKEN_KEY, token);
}

/** Remove the access token from localStorage. No-op on the server. */
export function clearToken(): void {
  if (!hasStorage()) return;
  window.localStorage.removeItem(ACCESS_TOKEN_KEY);
}

/** Base64url -> UTF-8 string, isomorphic (browser atob + TextDecoder, or Buffer). */
function base64UrlDecode(segment: string): string {
  let base64 = segment.replace(/-/g, "+").replace(/_/g, "/");
  const pad = base64.length % 4;
  if (pad) base64 += "=".repeat(4 - pad);

  if (typeof atob === "function") {
    const binary = atob(base64);
    const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
    return new TextDecoder().decode(bytes);
  }
  // Server / Node fallback.
  return Buffer.from(base64, "base64").toString("utf-8");
}

/**
 * Decode JWT claims WITHOUT verifying the signature. For client-side routing
 * only — never trust these claims for authorization decisions.
 * Throws if the token is malformed.
 */
export function decodeToken(token: string): TokenClaims {
  const parts = token.split(".");
  if (parts.length !== 3) {
    throw new Error("Malformed JWT: expected 3 segments");
  }
  let claims: TokenClaims;
  try {
    claims = JSON.parse(base64UrlDecode(parts[1])) as TokenClaims;
  } catch {
    throw new Error("Malformed JWT: could not decode claims");
  }
  return claims;
}
