"use client";

// Client-side route guard for dashboard pages.
//
// Redirects unauthenticated visitors to /login. This is a UX guard only — the
// gateway enforces real authorization on every request. Optionally checks that
// the token's role matches the expected role for the page and, if not, sends
// the user to their own dashboard.

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { getToken, decodeToken } from "@/lib/auth";
import { dashboardPathForRole } from "@/lib/routes";
import type { TokenClaims } from "@/lib/auth";

export interface AuthGuardState {
  ready: boolean;
  claims: TokenClaims | null;
}

/**
 * Guard a client page. Returns `{ ready, claims }`:
 * - `ready` flips true once the check has run (render your content then).
 * - `claims` are the decoded token claims, or null while redirecting.
 *
 * Pass `expectedRole` to keep users on their own dashboard.
 */
export function useAuthGuard(expectedRole?: string): AuthGuardState {
  const router = useRouter();
  const [state, setState] = useState<AuthGuardState>({ ready: false, claims: null });

  useEffect(() => {
    const token = getToken();
    if (!token) {
      router.replace("/login");
      return;
    }

    let claims: TokenClaims;
    try {
      claims = decodeToken(token);
    } catch {
      router.replace("/login");
      return;
    }

    if (expectedRole && claims.role !== expectedRole) {
      router.replace(dashboardPathForRole(claims.role));
      return;
    }

    setState({ ready: true, claims });
  }, [router, expectedRole]);

  return state;
}
