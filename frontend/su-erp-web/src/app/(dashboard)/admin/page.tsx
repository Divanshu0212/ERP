"use client";

import { useCallback, useEffect, useState } from "react";

import { DashboardShell } from "@/components/DashboardShell";
import { DataPanel } from "@/components/DataPanel";
import { api, ApiError } from "@/lib/api";
import { listItems, listTotal } from "@/lib/paginate";

// The admin console manages a single institution (the caller's tenant):
// institution identity, headline counts, the user roster, and user creation.
// The gateway enforces admin authorization and scopes every response to the
// caller's institution.

interface Institution {
  id: string;
  slug: string;
  name: string;
  is_active: boolean;
  created_at: string;
}

interface User {
  id: string;
  email: string;
  role: string;
  is_active: boolean;
  date_joined: string;
}

const ROLES = ["student", "faculty", "warden", "driver", "admin", "alumni"] as const;
type Role = (typeof ROLES)[number];

interface StatDef {
  key: string;
  label: string;
  path: string;
}

// Cross-service headline counts. Each service exposes a paginated list; we ask
// for a single row and read the envelope total. Users come from the auth
// service (tenant-scoped); the rest are other services fronted by the gateway.
const CROSS_STATS: StatDef[] = [
  { key: "invoices", label: "Invoices", path: "/api/v1/finance/invoices?limit=1" },
  { key: "allocations", label: "Allocations", path: "/api/v1/hostel/allocations?limit=1" },
  { key: "tickets", label: "Tickets", path: "/api/v1/grievance?limit=1" },
];

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return e instanceof Error ? e.message : "Something went wrong.";
}

function formatDate(value: string): string {
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString();
}

/** Pull a field-level message out of an ApiError's errors payload, if present. */
function fieldErrorMessage(e: unknown): string | null {
  if (!(e instanceof ApiError) || !e.errors || typeof e.errors !== "object") return null;
  const errors = e.errors as Record<string, unknown>;
  for (const value of Object.values(errors)) {
    if (typeof value === "string") return value;
    if (Array.isArray(value) && typeof value[0] === "string") return value[0];
  }
  return null;
}

interface StatState {
  count: number | null;
  error: string | null;
}

function StatCard({
  label,
  loading,
  state,
}: {
  label: string;
  loading: boolean;
  state?: StatState;
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-800 dark:bg-gray-950">
      <p className="text-sm font-medium text-gray-500 dark:text-gray-400">{label}</p>
      {loading ? (
        <p role="status" className="mt-2 text-sm text-gray-400">
          Loading…
        </p>
      ) : state?.error ? (
        <p role="alert" className="mt-2 text-sm text-red-600 dark:text-red-400">
          {state.error}
        </p>
      ) : (
        <p className="mt-2 text-3xl font-semibold tabular-nums text-gray-900 dark:text-gray-50">
          {state?.count ?? 0}
        </p>
      )}
    </div>
  );
}

function ActiveBadge({ active }: { active: boolean }) {
  const cls = active
    ? "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300"
    : "bg-gray-200 text-gray-600 dark:bg-gray-800 dark:text-gray-400";
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${cls}`}>
      {active ? "Active" : "Inactive"}
    </span>
  );
}

function InstitutionHeader() {
  const [inst, setInst] = useState<Institution | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await api.get<Institution>("/api/v1/auth/institution");
        if (!cancelled) setInst(data);
      } catch (e) {
        if (!cancelled) setError(errMsg(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-800 dark:bg-gray-950">
      {loading ? (
        <p role="status" className="text-sm text-gray-500 dark:text-gray-400">
          Loading institution…
        </p>
      ) : error ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : inst ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-50">
              {inst.name}
            </h2>
            <p className="mt-0.5 font-mono text-xs text-gray-500 dark:text-gray-400">
              {inst.slug}
            </p>
          </div>
          <ActiveBadge active={inst.is_active} />
        </div>
      ) : null}
    </div>
  );
}

function AdminContent() {
  // Headline counts: users (auth service) + cross-service totals, each isolated.
  const [statsLoading, setStatsLoading] = useState(true);
  const [userCount, setUserCount] = useState<StatState>({ count: null, error: null });
  const [crossStats, setCrossStats] = useState<Record<string, StatState>>({});

  // User roster.
  const [users, setUsers] = useState<User[]>([]);
  const [usersLoading, setUsersLoading] = useState(true);
  const [usersError, setUsersError] = useState<string | null>(null);

  // Add-user form.
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("student");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [formSuccess, setFormSuccess] = useState<string | null>(null);

  const loadCrossStats = useCallback(async () => {
    setStatsLoading(true);
    const results = await Promise.all(
      CROSS_STATS.map(async (s) => {
        try {
          const data = await api.get(s.path);
          return [s.key, { count: listTotal(data), error: null }] as const;
        } catch (e) {
          return [s.key, { count: null, error: errMsg(e) }] as const;
        }
      }),
    );
    setCrossStats(Object.fromEntries(results));
    setStatsLoading(false);
  }, []);

  // Loads the user roster and derives the Users headline count from the same
  // envelope, so the table and the card never disagree.
  const loadUsers = useCallback(async () => {
    setUsersLoading(true);
    setUsersError(null);
    try {
      const data = await api.get("/api/v1/auth/users");
      setUsers(listItems<User>(data));
      setUserCount({ count: listTotal(data), error: null });
    } catch (e) {
      setUsersError(errMsg(e));
      setUserCount({ count: null, error: errMsg(e) });
    } finally {
      setUsersLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadCrossStats();
    void loadUsers();
  }, [loadCrossStats, loadUsers]);

  const onSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setSubmitting(true);
      setFormError(null);
      setFormSuccess(null);
      try {
        const created = await api.post<{ email: string }>("/api/v1/auth/users", {
          email,
          role,
          password,
        });
        setEmail("");
        setRole("student");
        setPassword("");
        setFormSuccess(`Created user ${created?.email ?? email}.`);
        await loadUsers();
      } catch (err) {
        setFormError(fieldErrorMessage(err) ?? errMsg(err));
      } finally {
        setSubmitting(false);
      }
    },
    [email, role, password, loadUsers],
  );

  return (
    <>
      <InstitutionHeader />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Users" loading={usersLoading} state={userCount} />
        {CROSS_STATS.map((s) => (
          <StatCard
            key={s.key}
            label={s.label}
            loading={statsLoading}
            state={crossStats[s.key]}
          />
        ))}
      </div>

      <DataPanel
        title="Users"
        loading={usersLoading}
        error={usersError}
        isEmpty={users.length === 0}
        emptyLabel="No users yet."
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-gray-200 text-gray-500 dark:border-gray-800 dark:text-gray-400">
                <th className="py-2 pr-4 font-medium">Email</th>
                <th className="py-2 pr-4 font-medium">Role</th>
                <th className="py-2 pr-4 font-medium">Status</th>
                <th className="py-2 font-medium">Joined</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr
                  key={u.id}
                  className="border-b border-gray-100 last:border-0 dark:border-gray-900"
                >
                  <td className="py-2 pr-4">{u.email}</td>
                  <td className="py-2 pr-4 capitalize">{u.role}</td>
                  <td className="py-2 pr-4">
                    <ActiveBadge active={u.is_active} />
                  </td>
                  <td className="py-2 text-gray-500 dark:text-gray-400">
                    {formatDate(u.date_joined)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </DataPanel>

      <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-800 dark:bg-gray-950">
        <h2 className="mb-3 text-base font-semibold text-gray-900 dark:text-gray-50">
          Add User
        </h2>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div>
              <label
                htmlFor="new-user-email"
                className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300"
              >
                Email
              </label>
              <input
                id="new-user-email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
              />
            </div>
            <div>
              <label
                htmlFor="new-user-role"
                className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300"
              >
                Role
              </label>
              <select
                id="new-user-role"
                value={role}
                onChange={(e) => setRole(e.target.value as Role)}
                className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
              >
                {ROLES.map((r) => (
                  <option key={r} value={r} className="capitalize">
                    {r}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label
                htmlFor="new-user-password"
                className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300"
              >
                Password
              </label>
              <input
                id="new-user-password"
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
              />
            </div>
          </div>

          {formError && (
            <p role="alert" className="text-sm text-red-600 dark:text-red-400">
              {formError}
            </p>
          )}
          {formSuccess && (
            <p role="status" className="text-sm text-green-600 dark:text-green-400">
              {formSuccess}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300 disabled:text-gray-500 dark:disabled:bg-gray-800 dark:disabled:text-gray-500"
          >
            {submitting ? "Adding…" : "Add User"}
          </button>
        </form>
      </div>
    </>
  );
}

export default function AdminDashboard() {
  return (
    <DashboardShell title="Admin Dashboard" role="admin">
      <AdminContent />
    </DashboardShell>
  );
}
