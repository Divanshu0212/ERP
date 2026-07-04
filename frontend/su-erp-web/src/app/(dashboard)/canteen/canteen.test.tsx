// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const router = { replace: vi.fn(), push: vi.fn(), prefetch: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router, usePathname: () => "/" }));

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      ...actual.api,
      get: (...args: unknown[]) => get(...args),
      post: (...args: unknown[]) => post(...args),
    },
  };
});

// window.Razorpay is absent under jsdom — mock the checkout helper.
const openRazorpayCheckout = vi.fn();
vi.mock("@/lib/razorpay", () => ({
  openRazorpayCheckout: (...args: unknown[]) => openRazorpayCheckout(...args),
  toPaise: (amount: number | string) =>
    Math.round(parseFloat(String(amount)) * 100),
}));

import CanteenPage from "./page";
import { setToken } from "@/lib/auth";

function studentToken(): string {
  const payload = Buffer.from(
    JSON.stringify({ sub: "s1", role: "student", tenant: "acme" }),
  ).toString("base64url");
  return `h.${payload}.s`;
}

function defaultGet(path: string) {
  if (path.includes("/menu-items")) {
    return Promise.resolve({
      results: [
        { id: "m-1", name: "Veg Thali", price: "80.00", available: true },
        { id: "m-2", name: "Sold Out Item", price: "50.00", available: false },
      ],
      count: 2,
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

describe("CanteenPage", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    openRazorpayCheckout.mockReset();
    window.localStorage.clear();
    setToken(studentToken());
  });

  it("shows available menu items and my orders", async () => {
    get.mockImplementation(defaultGet);

    render(<CanteenPage />);

    expect(await screen.findByText("Veg Thali")).toBeInTheDocument();
    // Unavailable items are filtered out.
    expect(screen.queryByText("Sold Out Item")).not.toBeInTheDocument();
    expect(await screen.findByText("o-1")).toBeInTheDocument();
  });

  it("places an order directly in simulated mode (empty key_id, no widget)", async () => {
    get.mockImplementation(defaultGet);
    post.mockImplementation((path: string) => {
      if (path.includes("/orders/checkout")) {
        // Dev/simulated mode: backend returns an empty key_id.
        return Promise.resolve({ order_id: "", amount: "160.00", currency: "INR", key_id: "" });
      }
      return Promise.resolve({ id: "o-2", status: "placed" });
    });

    render(<CanteenPage />);
    await screen.findByText("Veg Thali");

    fireEvent.change(screen.getByLabelText("Quantity for Veg Thali"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Place order" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/orders/", {
        items: [{ menu_item_id: "m-1", quantity: 2 }],
      }),
    );
    // Empty key_id => the Razorpay widget is never opened.
    expect(openRazorpayCheckout).not.toHaveBeenCalled();
    expect(await screen.findByText("Order placed.")).toBeInTheDocument();
  });

  it("opens the Razorpay widget when a key_id is returned, then confirms the order", async () => {
    get.mockImplementation(defaultGet);
    post.mockImplementation((path: string) => {
      if (path.includes("/orders/checkout")) {
        return Promise.resolve({
          order_id: "order_xyz",
          amount: "160.00",
          currency: "INR",
          key_id: "rzp_test_123",
        });
      }
      return Promise.resolve({ id: "o-2", status: "placed" });
    });
    openRazorpayCheckout.mockImplementation((opts: { onSuccess: (r: unknown) => void }) => {
      opts.onSuccess({
        razorpay_order_id: "order_xyz",
        razorpay_payment_id: "pay_xyz",
        razorpay_signature: "sig_xyz",
      });
      return Promise.resolve();
    });

    render(<CanteenPage />);
    await screen.findByText("Veg Thali");

    fireEvent.change(screen.getByLabelText("Quantity for Veg Thali"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Place order" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/orders/", {
        items: [{ menu_item_id: "m-1", quantity: 2 }],
        razorpay_order_id: "order_xyz",
        razorpay_payment_id: "pay_xyz",
        razorpay_signature: "sig_xyz",
      }),
    );
    expect(openRazorpayCheckout).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("Order placed.")).toBeInTheDocument();
  });
});
