"use client";

import { useCallback, useEffect, useState } from "react";

import { DashboardShell } from "@/components/DashboardShell";
import { DataPanel } from "@/components/DataPanel";
import { api, ApiError } from "@/lib/api";
import { listItems } from "@/lib/paginate";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { Input } from "@/components/ui/Input";
import { Alert } from "@/components/ui/Alert";
import { StatusPill } from "@/components/ui/StatusPill";
import { Table, TBody, TD, TH, THead, HeaderRow, Row } from "@/components/ui/Table";

interface MenuItem {
  id: string;
  name: string;
  price: string;
  available: boolean;
  created_at: string;
}

interface OrderItem {
  id: string;
  menu_item_id: string;
  name: string;
  quantity: number;
  unit_price: string;
}

interface Order {
  id: string;
  student_id: string;
  status: string;
  total: string;
  items: OrderItem[];
  created_at: string;
}

// Legal order status transitions enforced by the backend; we only offer valid
// next steps.
const NEXT_STATUS: Record<string, string[]> = {
  placed: ["preparing", "cancelled"],
  preparing: ["ready", "cancelled"],
  ready: ["completed"],
};

function errMsg(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.errors && typeof e.errors === "object") {
      for (const v of Object.values(e.errors as Record<string, unknown>)) {
        if (Array.isArray(v) && v.length) return String(v[0]);
        if (typeof v === "string") return v;
      }
    }
    return e.message;
  }
  return e instanceof Error ? e.message : "Something went wrong.";
}

function MenuSection() {
  const [items, setItems] = useState<MenuItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [price, setPrice] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await api.get("/api/v1/menu-items/");
      setItems(listItems<MenuItem>(data));
    } catch (e) {
      setLoadError(errMsg(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function patchItem(id: string, body: Partial<Pick<MenuItem, "price" | "available">>) {
    setRowError(null);
    try {
      const updated = await api.patch<MenuItem>(`/api/v1/menu-items/${id}/`, body);
      setItems((prev) => prev.map((m) => (m.id === id ? { ...m, ...updated } : m)));
    } catch (e) {
      setRowError(errMsg(e));
    }
  }

  async function deleteItem(id: string, name: string) {
    if (!window.confirm(`Delete "${name}"? This cannot be undone.`)) return;
    setRowError(null);
    try {
      await api.delete(`/api/v1/menu-items/${id}/`);
      setItems((prev) => prev.filter((m) => m.id !== id));
    } catch (e) {
      setRowError(errMsg(e));
    }
  }

  async function createItem(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    setOk(null);
    try {
      await api.post("/api/v1/menu-items/", { name, price });
      setOk(`Added ${name}.`);
      setName("");
      setPrice("");
      await load();
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-6">
      <DataPanel
        title="Menu items"
        loading={loading}
        error={loadError}
        isEmpty={items.length === 0}
        emptyLabel="No menu items yet. Add one below."
      >
        {rowError && <Alert tone="error" className="mb-4">{rowError}</Alert>}
        <Table>
          <THead>
            <HeaderRow>
              <TH>Item</TH>
              <TH>Price</TH>
              <TH>Available</TH>
              <TH className="text-right">Actions</TH>
            </HeaderRow>
          </THead>
          <TBody>
            {items.map((m) => (
              <Row key={m.id}>
                <TD className="font-medium">{m.name}</TD>
                <TD>
                  <Input
                    aria-label={`Price for ${m.name}`}
                    defaultValue={m.price}
                    onBlur={(e) => {
                      if (e.target.value !== m.price) patchItem(m.id, { price: e.target.value });
                    }}
                    className="h-8 w-24"
                  />
                </TD>
                <TD>
                  <StatusPill status={m.available ? "available" : "unavailable"} tone={m.available ? "success" : "neutral"} />
                </TD>
                <TD className="text-right">
                  <div className="flex justify-end gap-2">
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => patchItem(m.id, { available: !m.available })}
                    >
                      {m.available ? "Mark unavailable" : "Mark available"}
                    </Button>
                    <Button size="sm" variant="danger" onClick={() => deleteItem(m.id, m.name)}>
                      Delete
                    </Button>
                  </div>
                </TD>
              </Row>
            ))}
          </TBody>
        </Table>
      </DataPanel>

      <Card>
        <CardHeader title="Add menu item" />
        <CardBody>
          <form onSubmit={createItem} className="space-y-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Name" htmlFor="mi-name">
                <Input id="mi-name" value={name} onChange={(e) => setName(e.target.value)} required />
              </Field>
              <Field label="Price" htmlFor="mi-price">
                <Input
                  id="mi-price"
                  value={price}
                  onChange={(e) => setPrice(e.target.value)}
                  placeholder="80.00"
                  required
                />
              </Field>
            </div>
            {error && <Alert tone="error">{error}</Alert>}
            {ok && <Alert tone="success">{ok}</Alert>}
            <Button type="submit" loading={pending}>
              Add item
            </Button>
          </form>
        </CardBody>
      </Card>
    </div>
  );
}

function OrdersSection() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await api.get("/api/v1/orders/");
      setOrders(listItems<Order>(data));
    } catch (e) {
      setLoadError(errMsg(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function advance(id: string, status: string) {
    setRowError(null);
    try {
      const updated = await api.patch<Order>(`/api/v1/orders/${id}/status/`, { status });
      setOrders((prev) => prev.map((o) => (o.id === id ? { ...o, ...updated } : o)));
    } catch (e) {
      setRowError(errMsg(e));
    }
  }

  return (
    <DataPanel
      title="Orders queue"
      loading={loading}
      error={loadError}
      isEmpty={orders.length === 0}
      emptyLabel="No orders in the last 30 days."
    >
      {rowError && <Alert tone="error" className="mb-4">{rowError}</Alert>}
      <Table>
        <THead>
          <HeaderRow>
            <TH>Order</TH>
            <TH>Items</TH>
            <TH>Total</TH>
            <TH>Status</TH>
            <TH className="text-right">Advance</TH>
          </HeaderRow>
        </THead>
        <TBody>
          {orders.map((o) => {
            const next = NEXT_STATUS[o.status] ?? [];
            return (
              <Row key={o.id}>
                <TD className="font-mono text-[12px]">{o.id}</TD>
                <TD className="text-muted">
                  {o.items.map((i) => `${i.name} x${i.quantity}`).join(", ")}
                </TD>
                <TD className="tabular-nums">{o.total}</TD>
                <TD>
                  <StatusPill status={o.status} />
                </TD>
                <TD className="text-right">
                  <div className="flex justify-end gap-2">
                    {next.length === 0 ? (
                      <span className="text-[12px] text-muted">—</span>
                    ) : (
                      next.map((s) => (
                        <Button
                          key={s}
                          size="sm"
                          variant={s === "cancelled" ? "danger" : "primary"}
                          onClick={() => advance(o.id, s)}
                        >
                          {s}
                        </Button>
                      ))
                    )}
                  </div>
                </TD>
              </Row>
            );
          })}
        </TBody>
      </Table>
    </DataPanel>
  );
}

export default function CanteenOwnerDashboard() {
  return (
    <DashboardShell title="Canteen" role="canteen_owner">
      <div className="space-y-6">
        <MenuSection />
        <OrdersSection />
      </div>
    </DashboardShell>
  );
}
