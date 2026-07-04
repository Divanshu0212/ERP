"use client";

import { useCallback, useEffect, useState } from "react";

import { DashboardShell } from "@/components/DashboardShell";
import { DataPanel } from "@/components/DataPanel";
import { api, ApiError } from "@/lib/api";
import { listItems } from "@/lib/paginate";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
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

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return e instanceof Error ? e.message : "Something went wrong.";
}

function CanteenContent() {
  const [menu, setMenu] = useState<MenuItem[]>([]);
  const [menuLoading, setMenuLoading] = useState(true);
  const [menuError, setMenuError] = useState<string | null>(null);

  const [orders, setOrders] = useState<Order[]>([]);
  const [ordersLoading, setOrdersLoading] = useState(true);
  const [ordersError, setOrdersError] = useState<string | null>(null);

  // Cart: menu_item_id -> quantity.
  const [cart, setCart] = useState<Record<string, number>>({});
  const [placing, setPlacing] = useState(false);
  const [placeError, setPlaceError] = useState<string | null>(null);
  const [placeOk, setPlaceOk] = useState<string | null>(null);

  const loadMenu = useCallback(async () => {
    setMenuLoading(true);
    setMenuError(null);
    try {
      const data = await api.get("/api/v1/menu-items/");
      setMenu(listItems<MenuItem>(data).filter((m) => m.available));
    } catch (e) {
      setMenuError(errMsg(e));
    } finally {
      setMenuLoading(false);
    }
  }, []);

  const loadOrders = useCallback(async () => {
    setOrdersLoading(true);
    setOrdersError(null);
    try {
      const data = await api.get("/api/v1/orders/");
      setOrders(listItems<Order>(data));
    } catch (e) {
      setOrdersError(errMsg(e));
    } finally {
      setOrdersLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadMenu();
    void loadOrders();
  }, [loadMenu, loadOrders]);

  function setQty(id: string, qty: number) {
    setCart((prev) => {
      const next = { ...prev };
      if (qty <= 0) delete next[id];
      else next[id] = qty;
      return next;
    });
  }

  const cartEntries = Object.entries(cart);

  async function placeOrder() {
    setPlacing(true);
    setPlaceError(null);
    setPlaceOk(null);
    try {
      const items = cartEntries.map(([menu_item_id, quantity]) => ({ menu_item_id, quantity }));
      await api.post("/api/v1/orders/", { items });
      setPlaceOk("Order placed.");
      setCart({});
      await loadOrders();
    } catch (e) {
      setPlaceError(errMsg(e));
    } finally {
      setPlacing(false);
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title="Menu" />
        <CardBody>
          {menuLoading ? (
            <p role="status" className="text-[13px] text-muted">
              Loading…
            </p>
          ) : menuError ? (
            <p role="alert" className="text-[13px] text-danger">
              {menuError}
            </p>
          ) : menu.length === 0 ? (
            <p className="text-[13px] text-muted">No items available.</p>
          ) : (
            <>
              <Table>
                <THead>
                  <HeaderRow>
                    <TH>Item</TH>
                    <TH>Price</TH>
                    <TH className="text-right">Quantity</TH>
                  </HeaderRow>
                </THead>
                <TBody>
                  {menu.map((m) => (
                    <Row key={m.id}>
                      <TD className="font-medium">{m.name}</TD>
                      <TD className="tabular-nums">{m.price}</TD>
                      <TD className="text-right">
                        <Input
                          type="number"
                          min={0}
                          aria-label={`Quantity for ${m.name}`}
                          value={cart[m.id] ?? 0}
                          onChange={(e) => setQty(m.id, Number(e.target.value))}
                          className="ml-auto h-8 w-20 text-right"
                        />
                      </TD>
                    </Row>
                  ))}
                </TBody>
              </Table>
              {placeError && <Alert tone="error" className="mt-4">{placeError}</Alert>}
              {placeOk && <Alert tone="success" className="mt-4">{placeOk}</Alert>}
              <div className="mt-4">
                <Button
                  onClick={placeOrder}
                  loading={placing}
                  disabled={cartEntries.length === 0}
                >
                  Place order
                </Button>
              </div>
            </>
          )}
        </CardBody>
      </Card>

      <DataPanel
        title="My orders"
        loading={ordersLoading}
        error={ordersError}
        isEmpty={orders.length === 0}
        emptyLabel="No orders in the last 30 days."
      >
        <Table>
          <THead>
            <HeaderRow>
              <TH>Order</TH>
              <TH>Items</TH>
              <TH>Total</TH>
              <TH>Status</TH>
            </HeaderRow>
          </THead>
          <TBody>
            {orders.map((o) => (
              <Row key={o.id}>
                <TD className="font-mono text-[12px]">{o.id}</TD>
                <TD className="text-muted">
                  {o.items.map((i) => `${i.name} x${i.quantity}`).join(", ")}
                </TD>
                <TD className="tabular-nums">{o.total}</TD>
                <TD>
                  <StatusPill status={o.status} />
                </TD>
              </Row>
            ))}
          </TBody>
        </Table>
      </DataPanel>
    </div>
  );
}

export default function CanteenPage() {
  return (
    <DashboardShell title="Canteen" role="student">
      <CanteenContent />
    </DashboardShell>
  );
}
