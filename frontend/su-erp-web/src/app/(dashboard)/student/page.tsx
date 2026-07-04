"use client";

import { useCallback, useEffect, useState } from "react";

import { DashboardShell } from "@/components/DashboardShell";
import { DataPanel } from "@/components/DataPanel";
import { api, ApiError } from "@/lib/api";
import { listItems } from "@/lib/paginate";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { StatusPill } from "@/components/ui/StatusPill";
import { Table, TBody, TD, TH, THead, HeaderRow, Row } from "@/components/ui/Table";

interface Invoice {
  id: string;
  amount: number;
  status: string;
  purpose: string;
  created_at: string;
}

interface Notification {
  id: string;
  title: string;
  body: string;
  created_at: string;
}

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return e instanceof Error ? e.message : "Something went wrong.";
}

function formatAmount(amount: number): string {
  return typeof amount === "number" ? amount.toLocaleString() : String(amount);
}

function formatDate(value: string): string {
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString();
}

function isPaid(status: string): boolean {
  return ["paid", "completed", "settled"].includes((status || "").toLowerCase());
}

function StudentContent() {
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [invoicesLoading, setInvoicesLoading] = useState(true);
  const [invoicesError, setInvoicesError] = useState<string | null>(null);

  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [notifLoading, setNotifLoading] = useState(true);
  const [notifError, setNotifError] = useState<string | null>(null);

  const loadInvoices = useCallback(async () => {
    setInvoicesLoading(true);
    setInvoicesError(null);
    try {
      const data = await api.get("/api/v1/finance/invoices");
      setInvoices(listItems<Invoice>(data));
    } catch (e) {
      setInvoicesError(errMsg(e));
    } finally {
      setInvoicesLoading(false);
    }
  }, []);

  const loadNotifications = useCallback(async () => {
    setNotifLoading(true);
    setNotifError(null);
    try {
      const data = await api.get("/api/v1/notify/inbox");
      setNotifications(listItems<Notification>(data));
    } catch (e) {
      setNotifError(errMsg(e));
    } finally {
      setNotifLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadInvoices();
    void loadNotifications();
  }, [loadInvoices, loadNotifications]);

  return (
    <div className="space-y-6">
      <DataPanel
        title="Fees & invoices"
        loading={invoicesLoading}
        error={invoicesError}
        isEmpty={invoices.length === 0}
        emptyLabel="No invoices yet."
      >
        <Table>
          <THead>
            <HeaderRow>
              <TH>Purpose</TH>
              <TH>Amount</TH>
              <TH>Status</TH>
              <TH className="text-right">Action</TH>
            </HeaderRow>
          </THead>
          <TBody>
            {invoices.map((inv) => (
              <Row key={inv.id}>
                <TD className="font-medium">{inv.purpose}</TD>
                <TD className="tabular-nums">{formatAmount(inv.amount)}</TD>
                <TD>
                  <StatusPill status={inv.status} />
                </TD>
                <TD className="text-right">
                  <Button
                    size="sm"
                    variant={isPaid(inv.status) ? "secondary" : "primary"}
                    disabled={isPaid(inv.status)}
                  >
                    {isPaid(inv.status) ? "Paid" : "Pay"}
                  </Button>
                </TD>
              </Row>
            ))}
          </TBody>
        </Table>
      </DataPanel>

      <DataPanel
        title="Notifications"
        loading={notifLoading}
        error={notifError}
        isEmpty={notifications.length === 0}
        emptyLabel="No notifications."
      >
        <ul className="space-y-2">
          {notifications.map((n) => (
            <li key={n.id} className="rounded-md border border-line p-3">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-medium text-ink">{n.title}</p>
                <span className="shrink-0 text-[11px] text-muted">{formatDate(n.created_at)}</span>
              </div>
              <p className="mt-1 text-[13px] text-muted">{n.body}</p>
            </li>
          ))}
        </ul>
      </DataPanel>

      <Card>
        <CardHeader title="Grievances" />
        <CardBody>
          <p className="text-[13px] text-muted">
            Have an issue? Raise a grievance and track it to resolution.
          </p>
          <Button className="mt-3" size="sm">
            Raise Grievance
          </Button>
        </CardBody>
      </Card>
    </div>
  );
}

export default function StudentDashboard() {
  return (
    <DashboardShell title="Overview" role="student">
      <StudentContent />
    </DashboardShell>
  );
}
