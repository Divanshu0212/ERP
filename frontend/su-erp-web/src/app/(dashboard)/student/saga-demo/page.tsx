"use client";

import { useCallback, useEffect, useState } from "react";

import { DashboardShell } from "@/components/DashboardShell";
import { DataPanel } from "@/components/DataPanel";
import { api, ApiError } from "@/lib/api";
import { listItems } from "@/lib/paginate";
import { usePoll } from "@/lib/usePoll";
import { cn } from "@/lib/cn";
import { Card, CardBody } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { StatusPill } from "@/components/ui/StatusPill";
import { Table, TBody, TD, TH, THead, HeaderRow, Row } from "@/components/ui/Table";

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

function AllocationStatus({ status }: { status: string }) {
  return <StatusPill status={isConfirmed(status) ? "Confirmed" : "Pending"} />;
}

function SagaDemoContent() {
  const [allocations, setAllocations] = useState<Allocation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [activeId, setActiveId] = useState<string | null>(null);
  const [payError, setPayError] = useState<string | null>(null);

  const poll = usePoll<Allocation>({
    fetcher: async () => api.get<Allocation>(`/api/v1/hostel/allocations/${activeId}`),
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
        poll.start();
      } catch (e) {
        setPayError(errMsg(e));
      }
    },
    [poll],
  );

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
    <div className="space-y-6">
      <Card>
        <CardBody className="text-[13px] text-muted">
          Pay a hostel fee and watch the allocation saga flip the booking from{" "}
          <span className="font-medium text-warn">pending</span> to{" "}
          <span className="font-medium text-success">confirmed</span> once the payment
          settles.
        </CardBody>
      </Card>

      <DataPanel
        title="Pending allocations"
        loading={loading}
        error={error}
        isEmpty={allocations.length === 0}
        emptyLabel="No pending allocations."
      >
        <Table>
          <THead>
            <HeaderRow>
              <TH>Allocation</TH>
              <TH>Room</TH>
              <TH>Status</TH>
              <TH className="text-right">Action</TH>
            </HeaderRow>
          </THead>
          <TBody>
            {allocations.map((a) => {
              const active = a.id === activeId;
              const shownStatus = active && poll.data ? poll.data.status : a.status;
              const busy = active && poll.status === "polling";
              return (
                <Row key={a.id}>
                  <TD className="font-mono text-[12px]">{a.id}</TD>
                  <TD className="font-medium">{a.room}</TD>
                  <TD>
                    <AllocationStatus status={shownStatus} />
                  </TD>
                  <TD className="text-right">
                    <Button
                      size="sm"
                      loading={busy}
                      disabled={busy || isConfirmed(shownStatus)}
                      onClick={() => void payAndConfirm(a)}
                    >
                      {busy ? "Confirming…" : "Pay & Confirm"}
                    </Button>
                  </TD>
                </Row>
              );
            })}
          </TBody>
        </Table>

        {pollingLabel && (
          <p
            role="status"
            className={cn(
              "mt-3 text-[13px]",
              poll.status === "done"
                ? "text-success"
                : poll.status === "timeout" || poll.status === "error"
                  ? "text-danger"
                  : "text-muted",
            )}
          >
            {pollingLabel}
          </p>
        )}
        {payError && (
          <p role="alert" className="mt-2 text-[13px] text-danger">
            {payError}
          </p>
        )}
      </DataPanel>
    </div>
  );
}

export default function SagaDemoPage() {
  return (
    <DashboardShell title="Pay & confirm" role="student">
      <SagaDemoContent />
    </DashboardShell>
  );
}
