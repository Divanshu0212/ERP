"use client";

import { useCallback, useEffect, useState } from "react";

import { DashboardShell } from "@/components/DashboardShell";
import { DataPanel } from "@/components/DataPanel";
import { api, ApiError } from "@/lib/api";
import { listItems } from "@/lib/paginate";
import { openRazorpayCheckout, toPaise } from "@/lib/razorpay";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { Select } from "@/components/ui/Select";
import { Alert } from "@/components/ui/Alert";
import { StatusPill } from "@/components/ui/StatusPill";
import { Table, TBody, TD, TH, THead, HeaderRow, Row } from "@/components/ui/Table";

interface RazorpayOrder {
  order_id: string;
  amount: number | string;
  currency: string;
  key_id: string;
}

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

interface AvailableRoom {
  id: string;
  block_name: string;
  room_no: string;
  is_available: boolean;
}

interface RoomRequest {
  id: string;
  room_id: string;
  room_name: string;
  status: string;
  requested_on: string;
  rejection_reason: string;
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

function newIdempotencyKey(): string {
  return typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `idem-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function StudentContent() {
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [invoicesLoading, setInvoicesLoading] = useState(true);
  const [invoicesError, setInvoicesError] = useState<string | null>(null);

  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [notifLoading, setNotifLoading] = useState(true);
  const [notifError, setNotifError] = useState<string | null>(null);

  const [payingId, setPayingId] = useState<string | null>(null);
  const [payError, setPayError] = useState<string | null>(null);
  const [payOk, setPayOk] = useState<string | null>(null);

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

  const settlePayment = useCallback(
    async (invoiceId: string, idempotencyKey: string, razorpay?: {
      razorpay_order_id: string;
      razorpay_payment_id: string;
      razorpay_signature: string;
    }) => {
      await api.post("/api/v1/finance/pay", {
        invoice_id: invoiceId,
        idempotency_key: idempotencyKey,
        ...(razorpay ?? {}),
      });
      setPayOk("Payment successful.");
      await loadInvoices();
    },
    [loadInvoices],
  );

  const payInvoice = useCallback(
    async (inv: Invoice) => {
      setPayError(null);
      setPayOk(null);
      setPayingId(inv.id);
      const idempotencyKey = newIdempotencyKey();

      let order: RazorpayOrder;
      try {
        order = await api.post<RazorpayOrder>(
          `/api/v1/finance/invoices/${inv.id}/razorpay-order`,
        );
      } catch (e) {
        // Razorpay not configured server-side (400) — fall back to the old
        // simulated direct-pay flow so local/demo environments keep working.
        if (e instanceof ApiError && e.status === 400) {
          try {
            await settlePayment(inv.id, idempotencyKey);
          } catch (payErr) {
            setPayError(errMsg(payErr));
          } finally {
            setPayingId(null);
          }
          return;
        }
        setPayError(errMsg(e));
        setPayingId(null);
        return;
      }

      await openRazorpayCheckout({
        keyId: order.key_id,
        orderId: order.order_id,
        amountPaise: toPaise(order.amount),
        currency: order.currency,
        name: "SU-ERP",
        description: inv.purpose,
        onSuccess: (res) => {
          void (async () => {
            try {
              await settlePayment(inv.id, idempotencyKey, res);
            } catch (payErr) {
              setPayError(errMsg(payErr));
            } finally {
              setPayingId(null);
            }
          })();
        },
        onDismiss: () => setPayingId(null),
        onError: (msg) => {
          setPayError(msg);
          setPayingId(null);
        },
      });
    },
    [settlePayment],
  );

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
                  <div className="flex items-center justify-end gap-2">
                    <Button
                      size="sm"
                      variant={isPaid(inv.status) ? "secondary" : "primary"}
                      loading={payingId === inv.id}
                      disabled={isPaid(inv.status) || payingId === inv.id}
                      onClick={() => void payInvoice(inv)}
                    >
                      {isPaid(inv.status) ? "Paid" : "Pay"}
                    </Button>
                    {isPaid(inv.status) && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          void api.download(
                            `/api/v1/finance/receipts/by-invoice/${inv.id}/pdf`,
                            `receipt-${inv.id}.pdf`,
                          )
                        }
                      >
                        Download receipt
                      </Button>
                    )}
                  </div>
                </TD>
              </Row>
            ))}
          </TBody>
        </Table>
        {payError && <Alert tone="error" className="mt-4">{payError}</Alert>}
        {payOk && <Alert tone="success" className="mt-4">{payOk}</Alert>}
      </DataPanel>

      <RoomRequestPanel />

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

function RoomRequestPanel() {
  const [rooms, setRooms] = useState<AvailableRoom[]>([]);
  const [myRequests, setMyRequests] = useState<RoomRequest[]>([]);
  const [selectedRoomId, setSelectedRoomId] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [roomsData, requestsData] = await Promise.all([
        api.get("/api/v1/hostel/rooms/available"),
        api.get("/api/v1/hostel/room-requests/mine"),
      ]);
      setRooms(listItems<AvailableRoom>(roomsData));
      setMyRequests(listItems<RoomRequest>(requestsData));
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedRoomId) return;
    setPending(true);
    setError(null);
    try {
      await api.post("/api/v1/hostel/room-requests", { room_id: selectedRoomId });
      setSelectedRoomId("");
      await load();
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Request a room" />
      <CardBody>
        <form onSubmit={submit} className="space-y-4">
          <Field label="Room" htmlFor="room-select">
            <Select
              id="room-select"
              value={selectedRoomId}
              onChange={(e) => setSelectedRoomId(e.target.value)}
            >
              <option value="">Select a room…</option>
              {rooms.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.block_name} - {r.room_no}
                </option>
              ))}
            </Select>
          </Field>
          {error && <Alert tone="error">{error}</Alert>}
          <Button type="submit" loading={pending} disabled={!selectedRoomId}>
            Request
          </Button>
        </form>

        <div className="mt-6">
          <DataPanel
            title="My requests"
            loading={loading}
            error={null}
            isEmpty={myRequests.length === 0}
            emptyLabel="No room requests yet."
          >
            <Table>
              <THead>
                <HeaderRow>
                  <TH>Room</TH>
                  <TH>Requested</TH>
                  <TH>Status</TH>
                  <TH>Note</TH>
                </HeaderRow>
              </THead>
              <TBody>
                {myRequests.map((r) => (
                  <Row key={r.id}>
                    <TD className="font-medium">{r.room_name}</TD>
                    <TD className="text-muted">{new Date(r.requested_on).toLocaleString()}</TD>
                    <TD>
                      <StatusPill status={r.status} />
                    </TD>
                    <TD className="text-muted">{r.rejection_reason}</TD>
                  </Row>
                ))}
              </TBody>
            </Table>
          </DataPanel>
        </div>
      </CardBody>
    </Card>
  );
}

export default function StudentDashboard() {
  return (
    <DashboardShell title="Overview" role="student">
      <StudentContent />
    </DashboardShell>
  );
}
