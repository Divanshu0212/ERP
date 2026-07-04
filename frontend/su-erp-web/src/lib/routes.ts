// Role -> dashboard route mapping for post-login redirects and route guards.
//
// Roles come from decoded JWT claims (client-side routing only; the gateway
// performs real authorization). Unknown roles fall back to the student view.

/** Roles the frontend recognises for routing. */
export type Role = "student" | "warden" | "admin" | "superadmin";

/** Dashboard base paths, keyed by role. */
export const DASHBOARD_PATHS: Record<Role, string> = {
  student: "/student",
  warden: "/warden",
  admin: "/admin",
  superadmin: "/superadmin",
};

/** All dashboard base paths (used by the auth guard to detect protected routes). */
export const DASHBOARD_BASES: string[] = Object.values(DASHBOARD_PATHS);

/**
 * Resolve the dashboard path for a role claim. Unknown/empty roles route to the
 * student dashboard as a safe default.
 */
export function dashboardPathForRole(role: string | undefined | null): string {
  if (role && role in DASHBOARD_PATHS) {
    return DASHBOARD_PATHS[role as Role];
  }
  return DASHBOARD_PATHS.student;
}
