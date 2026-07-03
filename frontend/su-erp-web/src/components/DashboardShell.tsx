"use client";

import { useAuthGuard } from "@/lib/useAuthGuard";
import { LogoutButton } from "@/components/LogoutButton";

import type { ReactNode } from "react";

import type { TokenClaims } from "@/lib/auth";

/**
 * Dashboard shell: guards the route (redirect to /login when unauthenticated or
 * wrong role), renders a heading + logout button, then renders `children`.
 *
 * When `children` is a function it receives the decoded token claims so pages
 * can key data fetches off `claims.sub` / `claims.tenant`. With no children the
 * shell shows a "Signed in as …" placeholder.
 */
export function DashboardShell({
  title,
  role,
  children,
}: {
  title: string;
  role: string;
  children?: ReactNode | ((claims: TokenClaims) => ReactNode);
}) {
  const { ready, claims } = useAuthGuard(role);

  if (!ready) {
    return (
      <main className="flex min-h-screen items-center justify-center text-sm text-gray-500">
        Loading…
      </main>
    );
  }

  const body =
    typeof children === "function"
      ? claims
        ? children(claims)
        : null
      : children ?? <p>Signed in as {claims?.sub ?? "unknown"}.</p>;

  return (
    <main className="min-h-screen bg-gray-50 dark:bg-black">
      <header className="flex items-center justify-between border-b border-gray-200 bg-white px-6 py-4 dark:border-gray-800 dark:bg-gray-950">
        <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-50">{title}</h1>
        <div className="flex items-center gap-3">
          {claims?.tenant && (
            <span className="text-sm text-gray-500 dark:text-gray-400">{claims.tenant}</span>
          )}
          <LogoutButton />
        </div>
      </header>
      <section className="space-y-8 p-6 text-gray-700 dark:text-gray-300">{body}</section>
    </main>
  );
}
