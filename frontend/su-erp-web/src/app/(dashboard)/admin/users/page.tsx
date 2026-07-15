"use client";

import { useCallback, useEffect, useState } from "react";

import { DashboardShell } from "@/components/DashboardShell";
import { api, ApiError } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Alert";
import { StatusPill } from "@/components/ui/StatusPill";
import { Table, TBody, TD, TH, THead, HeaderRow, Row } from "@/components/ui/Table";

interface AdminUser {
  user_code: string;
  email: string;
  role: string;
  is_active: boolean;
  date_joined: string;
}

interface UserListResponse {
  results: AdminUser[];
  count: number;
}

interface BulkDeleteResult {
  deactivated: { user_code: string; email: string }[];
  failed: { user_code: string; error: string }[];
}

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return e instanceof Error ? e.message : "Something went wrong.";
}

async function fetchUsers(showInactive: boolean): Promise<AdminUser[]> {
  const query = showInactive ? "" : "&is_active=true";
  const resp = await api.get<UserListResponse>(`/api/v1/auth/users?page_size=100${query}`);
  return resp.results;
}

function AdminUsersContent() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [showInactive, setShowInactive] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BulkDeleteResult | null>(null);

  const load = useCallback(async (inactive: boolean) => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchUsers(inactive);
      setUsers(data);
      setSelected(new Set());
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(showInactive);
  }, [load, showInactive]);

  const toggleRow = useCallback((code: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  }, []);

  const toggleAll = useCallback(() => {
    setSelected((prev) => (prev.size === users.length ? new Set() : new Set(users.map((u) => u.user_code))));
  }, [users]);

  const onConfirmDelete = useCallback(async () => {
    setDeleting(true);
    setError(null);
    setResult(null);
    try {
      const data = await api.post<BulkDeleteResult>("/api/v1/auth/users/bulk-delete/", {
        user_codes: Array.from(selected),
      });
      setResult(data);
      setConfirming(false);
      await load(showInactive);
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setDeleting(false);
    }
  }, [selected, load, showInactive]);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title="Users" />
        <CardBody>
          <div className="mb-4 flex items-center justify-between gap-4">
            <label className="flex items-center gap-2 text-[13px] text-muted">
              <input
                type="checkbox"
                checked={showInactive}
                onChange={(e) => setShowInactive(e.target.checked)}
              />
              Show inactive users
            </label>
            <Button
              variant="danger"
              disabled={selected.size === 0}
              onClick={() => setConfirming(true)}
            >
              Delete selected ({selected.size})
            </Button>
          </div>

          {confirming && (
            <Alert tone="error" className="mb-4">
              <div className="flex items-center justify-between gap-4">
                <span>Deactivate {selected.size} user(s)? They will be logged out and unable to sign in.</span>
                <div className="flex gap-2">
                  <Button size="sm" variant="danger" loading={deleting} onClick={onConfirmDelete}>
                    Confirm
                  </Button>
                  <Button size="sm" variant="secondary" disabled={deleting} onClick={() => setConfirming(false)}>
                    Cancel
                  </Button>
                </div>
              </div>
            </Alert>
          )}

          {error && <Alert tone="error" className="mb-4">{error}</Alert>}
          {result && (
            <Alert tone={result.failed.length > 0 ? "info" : "success"} className="mb-4">
              {result.deactivated.length} user(s) deactivated, {result.failed.length} failed.
              {result.failed.map((f) => (
                <div key={f.user_code} className="text-[13px]">
                  {f.user_code}: {f.error}
                </div>
              ))}
            </Alert>
          )}

          {loading ? (
            <p className="text-[13px] text-muted">Loading…</p>
          ) : (
            <Table>
              <THead>
                <HeaderRow>
                  <TH>
                    <input
                      type="checkbox"
                      aria-label="Select all"
                      checked={users.length > 0 && selected.size === users.length}
                      onChange={toggleAll}
                    />
                  </TH>
                  <TH>User code</TH>
                  <TH>Email</TH>
                  <TH>Role</TH>
                  <TH>Status</TH>
                  <TH>Joined</TH>
                </HeaderRow>
              </THead>
              <TBody>
                {users.map((u) => (
                  <Row key={u.user_code}>
                    <TD>
                      <input
                        type="checkbox"
                        aria-label={`Select ${u.email}`}
                        checked={selected.has(u.user_code)}
                        onChange={() => toggleRow(u.user_code)}
                      />
                    </TD>
                    <TD className="font-medium">{u.user_code}</TD>
                    <TD>{u.email}</TD>
                    <TD className="capitalize">{u.role}</TD>
                    <TD>
                      <StatusPill status={u.is_active ? "active" : "inactive"} />
                    </TD>
                    <TD>{new Date(u.date_joined).toLocaleDateString()}</TD>
                  </Row>
                ))}
              </TBody>
            </Table>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

export default function AdminUsersPage() {
  return (
    <DashboardShell title="Users" role="admin">
      <AdminUsersContent />
    </DashboardShell>
  );
}
