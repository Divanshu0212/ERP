"use client";

import { useCallback, useEffect, useState } from "react";

import { DashboardShell } from "@/components/DashboardShell";
import { DataPanel } from "@/components/DataPanel";
import { api, ApiError } from "@/lib/api";
import { listItems, listTotal } from "@/lib/paginate";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { StatCard } from "@/components/ui/StatCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { Field } from "@/components/ui/Field";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Alert";
import { Table, TBody, TD, TH, THead, HeaderRow, Row } from "@/components/ui/Table";

// The admin console manages a single institution (the caller's tenant): headline
// counts, the user roster, and user creation. The institution identity lives in
// the app shell. The gateway scopes every response to the caller's institution.

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

// Cross-service headline counts: each service exposes a paginated list; we ask
// for one row and read the envelope total.
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

function AdminContent() {
  const [statsLoading, setStatsLoading] = useState(true);
  const [userCount, setUserCount] = useState<StatState>({ count: null, error: null });
  const [crossStats, setCrossStats] = useState<Record<string, StatState>>({});

  const [users, setUsers] = useState<User[]>([]);
  const [usersLoading, setUsersLoading] = useState(true);
  const [usersError, setUsersError] = useState<string | null>(null);

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

  // Derives the Users count from the roster envelope so table + card agree.
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
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Users" loading={usersLoading} error={userCount.error} value={userCount.count} />
        {CROSS_STATS.map((s) => (
          <StatCard
            key={s.key}
            label={s.label}
            loading={statsLoading}
            error={crossStats[s.key]?.error}
            value={crossStats[s.key]?.count ?? null}
          />
        ))}
      </div>

      <DataPanel
        title="Users"
        loading={usersLoading}
        error={usersError}
        isEmpty={users.length === 0}
        emptyLabel="No users yet. Add one below."
      >
        <Table>
          <THead>
            <HeaderRow>
              <TH>Email</TH>
              <TH>Role</TH>
              <TH>Status</TH>
              <TH>Joined</TH>
            </HeaderRow>
          </THead>
          <TBody>
            {users.map((u) => (
              <Row key={u.id}>
                <TD className="font-medium">{u.email}</TD>
                <TD className="capitalize text-muted">{u.role}</TD>
                <TD>
                  <StatusPill status={u.is_active ? "active" : "inactive"} />
                </TD>
                <TD className="text-muted">{formatDate(u.date_joined)}</TD>
              </Row>
            ))}
          </TBody>
        </Table>
      </DataPanel>

      <Card>
        <CardHeader title="Add user" />
        <CardBody>
          <form onSubmit={onSubmit} className="space-y-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <Field label="Email" htmlFor="new-user-email">
                <Input
                  id="new-user-email"
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </Field>
              <Field label="Role" htmlFor="new-user-role">
                <Select
                  id="new-user-role"
                  value={role}
                  onChange={(e) => setRole(e.target.value as Role)}
                >
                  {ROLES.map((r) => (
                    <option key={r} value={r} className="capitalize">
                      {r}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Password" htmlFor="new-user-password">
                <Input
                  id="new-user-password"
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </Field>
            </div>

            {formError && <Alert tone="error">{formError}</Alert>}
            {formSuccess && <Alert tone="success">{formSuccess}</Alert>}

            <Button type="submit" loading={submitting}>
              Add User
            </Button>
          </form>
        </CardBody>
      </Card>
    </div>
  );
}

export default function AdminDashboard() {
  return (
    <DashboardShell title="Admin" role="admin">
      <AdminContent />
    </DashboardShell>
  );
}
