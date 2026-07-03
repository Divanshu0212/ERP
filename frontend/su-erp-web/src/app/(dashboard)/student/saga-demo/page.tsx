"use client";

import { useCallback, useEffect, useState } from "react";

import { DashboardShell } from "@/components/DashboardShell";
import { DataPanel } from "@/components/DataPanel";
import { api, ApiError } from "@/lib/api";
import { listItems } from "@/lib/paginate";
import { usePoll } from "@/lib/usePoll";

// Saga demo: hostel allocation <-> finance.
//
// A student pays a hostel fee; the hostel-allocation saga confirms the
// allocation once payment settles. This page shows a pending allocation, a
// "Pay & Confirm" button, then polls the allocation until it flips to
// "confirmed" (2s interval, 10s timeout).

interface Allocation {
  id: string;
  student_id: string;
  room: string;
  status: string;
}

interface Invoice {
  id: string;
  amount: number;
  status: string;
}

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return e instanceof Error ? e.message : "Something went wrong.";
}

function isConfirmed(status: string): boolean {
  return ["confirmed", "allocated", "active"].includes((status || "").toLowerCase());
}

function StatusBadge({ status }: { status: string }) {
  const confirmed = isConfirmed(status);
  const cls = confirmed
    ? "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300"
    : "bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300";
  return (
    <span
      className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${cls}`}
    >
      {confirmed ? "Confirmed" : "Pending"}
    </span>
  );
}

function SagaDemoContent() {
  const [allocations, setAllocations] = useState<Allocation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // The allocation currently being paid/confirmed.
  const [activeId, setActiveId] = useState<string | null>(null);
  const [payError, setPayError] = useState<string | null>(null);

  const poll = usePoll<Allocation>({
    fetcher: async () => {
      const data = await api.get<Allocation>(`/api/v1/hostel/allocations/${activeId}`);
      return data;
    },
    isDone: (a) => isConfirmed(a.status),
    intervalMs: 2000,
    timeoutMs: 10000,
  });

  const loadAllocations = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get("/api/v1/hostel/allocations?status=pending");
      setAllocations(listItems<Allocation>(data));
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAllocations();
  }, [loadAllocations]);

  const payAndConfirm = useCallback(
    async (alloc: Allocation) => {
      setPayError(null);
      setActiveId(alloc.id);
      try {
        // Find the invoice for this allocation, then settle it. The saga
        // reacts to the payment event and confirms the allocation.
        const invoice = await api.get<Invoice>(
          `/api/v1/finance/invoices?allocation_id=${alloc.id}`,
        );
        const items = listItems<Invoice>(invoice);
        const target = items[0] ?? (invoice as Invoice);
        await api.post("/api/v1/finance/pay", {
          invoice_id: target?.id,
          allocation_id: alloc.id,
        });
        // Kick off polling — the fetcher reads activeId, already set above.
        poll.start();
      } catch (e) {
        setPayError(errMsg(e));
      }
    },
    [poll],
  );

  // When the saga confirms, refresh the pending list (the allocation drops off).
  useEffect(() => {
    if (poll.status === "done") {
      void loadAllocations();
    }
  }, [poll.status, loadAllocations]);

  const pollingLabel =
    poll.status === "polling"
      ? "Waiting for confirmation…"
      : poll.status === "timeout"
        ? "Timed out waiting for the saga to confirm. Try refreshing."
        : poll.status === "error"
          ? poll.error ?? "Polling failed."
          : poll.status === "done"
            ? "Allocation confirmed by the saga."
            : null;

  return (
    <>
      <div className="rounded-lg border border-gray-200 bg-white p-4 text-sm text-gray-600 shadow-sm dark:border-gray-800 dark:bg-gray-950 dark:text-gray-400">
        Pay a hostel fee and watch the allocation saga flip the booking from
        <span className="mx-1 font-medium text-orange-600 dark:text-orange-400">pending</span>
        to
        <span className="mx-1 font-medium text-green-600 dark:text-green-400">confirmed</span>
        once the payment settles.
      </div>

      <DataPanel
        title="Pending Allocations"
        loading={loading}
        error={error}
        isEmpty={allocations.length === 0}
        emptyLabel="No pending allocations."
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-gray-200 text-gray-500 dark:border-gray-800 dark:text-gray-400">
                <th className="py-2 pr-4 font-medium">Allocation</th>
                <th className="py-2 pr-4 font-medium">Room</th>
                <th className="py-2 pr-4 font-medium">Status</th>
                <th className="py-2 font-medium">Action</th>
              </tr>
            </thead>
            <tbody>
              {allocations.map((a) => {
                const active = a.id === activeId;
                const shownStatus =
                  active && poll.data ? poll.data.status : a.status;
                const busy = active && poll.status === "polling";
                return (
                  <tr
                    key={a.id}
                    className="border-b border-gray-100 last:border-0 dark:border-gray-900"
                  >
                    <td className="py-2 pr-4 font-mono text-xs">{a.id}</td>
                    <td className="py-2 pr-4">{a.room}</td>
                    <td className="py-2 pr-4">
                      <StatusBadge status={shownStatus} />
                    </td>
                    <td className="py-2">
                      <button
                        type="button"
                        disabled={busy || isConfirmed(shownStatus)}
                        onClick={() => void payAndConfirm(a)}
                        className="rounded-md bg-blue-600 px-3 py-1 text-xs font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300 disabled:text-gray-500 dark:disabled:bg-gray-800 dark:disabled:text-gray-500"
                      >
                        {busy ? "Confirming…" : "Pay & Confirm"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {pollingLabel && (
          <p
            role="status"
            className={`mt-3 text-sm ${
              poll.status === "done"
                ? "text-green-600 dark:text-green-400"
                : poll.status === "timeout" || poll.status === "error"
                  ? "text-red-600 dark:text-red-400"
                  : "text-gray-500 dark:text-gray-400"
            }`}
          >
            {pollingLabel}
          </p>
        )}
        {payError && (
          <p role="alert" className="mt-2 text-sm text-red-600 dark:text-red-400">
            {payError}
          </p>
        )}
      </DataPanel>
    </>
  );
}

export default function SagaDemoPage() {
  return (
    <DashboardShell title="Saga Demo · Hostel Payment" role="student">
      <SagaDemoContent />
    </DashboardShell>
  );
}
