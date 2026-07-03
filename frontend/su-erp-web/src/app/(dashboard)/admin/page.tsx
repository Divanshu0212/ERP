"use client";

import { useEffect, useState } from "react";

import { DashboardShell } from "@/components/DashboardShell";
import { api, ApiError } from "@/lib/api";
import { listTotal } from "@/lib/paginate";

interface StatDef {
  key: string;
  label: string;
  path: string;
}

// Each service exposes a paginated list; we ask for a single row and read the
// envelope's total count. The gateway enforces admin authorization.
const STATS: StatDef[] = [
  { key: "users", label: "Users", path: "/api/v1/users?limit=1" },
  { key: "invoices", label: "Invoices", path: "/api/v1/finance/invoices?limit=1" },
  { key: "allocations", label: "Allocations", path: "/api/v1/hostel/allocations?limit=1" },
  { key: "tickets", label: "Tickets", path: "/api/v1/grievance?limit=1" },
];

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return e instanceof Error ? e.message : "Something went wrong.";
}

interface StatState {
  count: number | null;
  error: string | null;
}

function AdminContent() {
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<Record<string, StatState>>({});

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      const results = await Promise.all(
        STATS.map(async (s) => {
          try {
            const data = await api.get(s.path);
            return [s.key, { count: listTotal(data), error: null }] as const;
          } catch (e) {
            return [s.key, { count: null, error: errMsg(e) }] as const;
          }
        }),
      );
      if (cancelled) return;
      setStats(Object.fromEntries(results));
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {STATS.map((s) => {
        const state = stats[s.key];
        return (
          <div
            key={s.key}
            className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-800 dark:bg-gray-950"
          >
            <p className="text-sm font-medium text-gray-500 dark:text-gray-400">{s.label}</p>
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
      })}
    </div>
  );
}

export default function AdminDashboard() {
  return (
    <DashboardShell title="Admin Dashboard" role="admin">
      <AdminContent />
    </DashboardShell>
  );
}
