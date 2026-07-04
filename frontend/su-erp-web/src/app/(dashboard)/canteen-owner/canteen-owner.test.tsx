// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const router = { replace: vi.fn(), push: vi.fn(), prefetch: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router, usePathname: () => "/" }));

const get = vi.fn();
const post = vi.fn();
const patch = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      ...actual.api,
      get: (...args: unknown[]) => get(...args),
      post: (...args: unknown[]) => post(...args),
      patch: (...args: unknown[]) => patch(...args),
    },
  };
});

import CanteenOwnerDashboard from "./page";
import { setToken } from "@/lib/auth";

function ownerToken(): string {
  const payload = Buffer.from(
    JSON.stringify({ sub: "c1", role: "canteen_owner", tenant: "acme" }),
  ).toString("base64url");
  return `h.${payload}.s`;
}

function defaultGet(path: string) {
  if (path.includes("/menu-items")) {
    return Promise.resolve({
      results: [{ id: "m-1", name: "Veg Thali", price: "80.00", available: true }],
      count: 1,
    });
  }
  if (path.includes("/orders")) {
    return Promise.resolve({
      results: [
        {
          id: "o-1",
          student_id: "s1",
          status: "placed",
          total: "80.00",
          items: [{ id: "oi-1", menu_item_id: "m-1", name: "Veg Thali", quantity: 1, unit_price: "80.00" }],
        },
      ],
      count: 1,
    });
  }
  return Promise.resolve({ results: [], count: 0 });
}

describe("CanteenOwnerDashboard", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    patch.mockReset();
    window.localStorage.clear();
    setToken(ownerToken());
  });

  it("renders menu items and the orders queue", async () => {
    get.mockImplementation(defaultGet);

    render(<CanteenOwnerDashboard />);

    expect(await screen.findByText("Veg Thali")).toBeInTheDocument();
    expect(await screen.findByText("o-1")).toBeInTheDocument();
    // Only legal next statuses for a placed order.
    expect(screen.getByRole("button", { name: "preparing" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "cancelled" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "ready" })).not.toBeInTheDocument();
  });

  it("advances an order status via PATCH", async () => {
    get.mockImplementation(defaultGet);
    patch.mockResolvedValue({ id: "o-1", status: "preparing" });

    render(<CanteenOwnerDashboard />);
    await screen.findByText("o-1");

    fireEvent.click(screen.getByRole("button", { name: "preparing" }));

    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith("/api/v1/orders/o-1/status/", { status: "preparing" }),
    );
  });

  it("creates a menu item", async () => {
    get.mockImplementation(defaultGet);
    post.mockResolvedValue({ id: "m-2", name: "Coffee", price: "20.00", available: true });

    render(<CanteenOwnerDashboard />);
    await screen.findByText("Veg Thali");

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Coffee" } });
    fireEvent.change(screen.getByLabelText("Price"), { target: { value: "20.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Add item" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/menu-items/", { name: "Coffee", price: "20.00" }),
    );
    expect(await screen.findByText("Added Coffee.")).toBeInTheDocument();
  });
});
