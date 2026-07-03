"use client";

import { useCallback, useEffect, useState } from "react";

import { DashboardShell } from "@/components/DashboardShell";
import { DataPanel } from "@/components/DataPanel";
import { api, ApiError } from "@/lib/api";
import { listItems } from "@/lib/paginate";

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
    <>
      <DataPanel
        title="Fees & Invoices"
        loading={invoicesLoading}
        error={invoicesError}
        isEmpty={invoices.length === 0}
        emptyLabel="No invoices yet."
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-gray-200 text-gray-500 dark:border-gray-800 dark:text-gray-400">
                <th className="py-2 pr-4 font-medium">Purpose</th>
                <th className="py-2 pr-4 font-medium">Amount</th>
                <th className="py-2 pr-4 font-medium">Status</th>
                <th className="py-2 font-medium">Action</th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((inv) => (
                <tr
                  key={inv.id}
                  className="border-b border-gray-100 last:border-0 dark:border-gray-900"
                >
                  <td className="py-2 pr-4">{inv.purpose}</td>
                  <td className="py-2 pr-4 tabular-nums">{formatAmount(inv.amount)}</td>
                  <td className="py-2 pr-4">
                    <span className="capitalize">{inv.status}</span>
                  </td>
                  <td className="py-2">
                    <button
                      type="button"
                      disabled={isPaid(inv.status)}
                      className="rounded-md bg-blue-600 px-3 py-1 text-xs font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300 disabled:text-gray-500 dark:disabled:bg-gray-800 dark:disabled:text-gray-500"
                    >
                      {isPaid(inv.status) ? "Paid" : "Pay"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </DataPanel>

      <DataPanel
        title="Notifications"
        loading={notifLoading}
        error={notifError}
        isEmpty={notifications.length === 0}
        emptyLabel="No notifications."
      >
        <ul className="space-y-3">
          {notifications.map((n) => (
            <li
              key={n.id}
              className="rounded-md border border-gray-100 p-3 dark:border-gray-900"
            >
              <div className="flex items-center justify-between gap-3">
                <p className="font-medium text-gray-900 dark:text-gray-100">{n.title}</p>
                <span className="shrink-0 text-xs text-gray-400">
                  {formatDate(n.created_at)}
                </span>
              </div>
              <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">{n.body}</p>
            </li>
          ))}
        </ul>
      </DataPanel>

      <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-800 dark:bg-gray-950">
        <h2 className="text-base font-semibold text-gray-900 dark:text-gray-50">Grievances</h2>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          Have an issue? Raise a grievance and track it to resolution.
        </p>
        <button
          type="button"
          className="mt-3 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
        >
          Raise Grievance
        </button>
      </div>
    </>
  );
}

export default function StudentDashboard() {
  return (
    <DashboardShell title="Student Dashboard" role="student">
      <StudentContent />
    </DashboardShell>
  );
}
