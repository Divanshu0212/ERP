// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, act, fireEvent } from "@testing-library/react";

// Stable router (useAuthGuard effect deps on it).
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

// window.Razorpay does not exist under jsdom, so mock the checkout helper. Tests
// drive onSuccess/onDismiss directly instead of loading the real script.
const openRazorpayCheckout = vi.fn();
vi.mock("@/lib/razorpay", () => ({
  openRazorpayCheckout: (...args: unknown[]) => openRazorpayCheckout(...args),
  toPaise: (amount: number | string) =>
    Math.round(parseFloat(String(amount)) * 100),
}));

import SagaDemoPage from "./page";
import { setToken } from "@/lib/auth";
import { ApiError } from "@/lib/api";

function studentToken(): string {
  const payload = Buffer.from(
    JSON.stringify({ sub: "u1", role: "student", tenant: "acme" }),
  ).toString("base64url");
  return `h.${payload}.s`;
}

describe("SagaDemoPage", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    openRazorpayCheckout.mockReset();
    window.localStorage.clear();
    setToken(studentToken());
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("pays via the Razorpay widget, verifies, polls, and flips to confirmed", async () => {
    let allocStatus = "pending";
    get.mockImplementation((path: string) => {
      if (path.includes("/hostel/allocations?status=pending")) {
        return Promise.resolve({
          items: [{ id: "alloc-1", student_id: "u1", room: "A-101", status: "pending" }],
          total: 1,
        });
      }
      if (path.includes("/finance/invoices?allocation_id=")) {
        return Promise.resolve({ items: [{ id: "inv-1", amount: 5000, status: "pending" }] });
      }
      if (path.includes("/hostel/allocations/alloc-1")) {
        return Promise.resolve({
          id: "alloc-1",
          student_id: "u1",
          room: "A-101",
          status: allocStatus,
        });
      }
      return Promise.resolve([]);
    });
    post.mockImplementation((path: string) => {
      if (path.includes("/razorpay-order")) {
        return Promise.resolve({
          order_id: "order_abc",
          amount: "5000.00",
          currency: "INR",
          key_id: "rzp_test_123",
        });
      }
      return Promise.resolve({ ok: true }); // /finance/pay
    });
    // Widget fires onSuccess synchronously with the razorpay_* fields.
    openRazorpayCheckout.mockImplementation((opts: { onSuccess: (r: unknown) => void }) => {
      opts.onSuccess({
        razorpay_order_id: "order_abc",
        razorpay_payment_id: "pay_abc",
        razorpay_signature: "sig_abc",
      });
      return Promise.resolve();
    });

    render(<SagaDemoPage />);

    const payBtn = await screen.findByRole("button", { name: /pay & confirm/i });
    expect(screen.getByText("Pending")).toBeInTheDocument();

    vi.useFakeTimers();
    fireEvent.click(payBtn);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    // Real verification path: pay POST carries the razorpay_* fields + idempotency key.
    expect(post).toHaveBeenCalledWith(
      "/api/v1/finance/pay",
      expect.objectContaining({
        invoice_id: "inv-1",
        allocation_id: "alloc-1",
        idempotency_key: expect.any(String),
        razorpay_order_id: "order_abc",
        razorpay_payment_id: "pay_abc",
        razorpay_signature: "sig_abc",
      }),
    );
    expect(screen.getByRole("status")).toHaveTextContent(/waiting for confirmation/i);

    allocStatus = "confirmed";
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(screen.getByRole("status")).toHaveTextContent(/confirmed by the saga/i);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
  });

  it("falls back to the simulated pay path when Razorpay is not configured", async () => {
    let allocStatus = "pending";
    get.mockImplementation((path: string) => {
      if (path.includes("/hostel/allocations?status=pending")) {
        return Promise.resolve({
          items: [{ id: "alloc-1", student_id: "u1", room: "A-101", status: "pending" }],
          total: 1,
        });
      }
      if (path.includes("/finance/invoices?allocation_id=")) {
        return Promise.resolve({ items: [{ id: "inv-1", amount: 5000, status: "pending" }] });
      }
      if (path.includes("/hostel/allocations/alloc-1")) {
        return Promise.resolve({
          id: "alloc-1",
          student_id: "u1",
          room: "A-101",
          status: allocStatus,
        });
      }
      return Promise.resolve([]);
    });
    post.mockImplementation((path: string) => {
      if (path.includes("/razorpay-order")) {
        return Promise.reject(new ApiError("Razorpay is not configured on this server.", 400));
      }
      return Promise.resolve({ ok: true });
    });

    render(<SagaDemoPage />);
    const payBtn = await screen.findByRole("button", { name: /pay & confirm/i });

    vi.useFakeTimers();
    fireEvent.click(payBtn);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    // Widget never opened; pay POST hit directly with idempotency key, no razorpay_* fields.
    expect(openRazorpayCheckout).not.toHaveBeenCalled();
    const payCall = post.mock.calls.find((c) => c[0] === "/api/v1/finance/pay");
    expect(payCall).toBeTruthy();
    expect(payCall![1]).toMatchObject({
      invoice_id: "inv-1",
      allocation_id: "alloc-1",
      idempotency_key: expect.any(String),
    });
    expect(payCall![1]).not.toHaveProperty("razorpay_order_id");
    expect(screen.getByRole("status")).toHaveTextContent(/waiting for confirmation/i);

    allocStatus = "confirmed";
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(screen.getByRole("status")).toHaveTextContent(/confirmed by the saga/i);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
  });

  it("times out when the saga never confirms", async () => {
    get.mockImplementation((path: string) => {
      if (path.includes("/hostel/allocations?status=pending")) {
        return Promise.resolve({
          items: [{ id: "alloc-2", student_id: "u1", room: "B-202", status: "pending" }],
          total: 1,
        });
      }
      if (path.includes("/finance/invoices?allocation_id=")) {
        return Promise.resolve({ items: [{ id: "inv-2", amount: 3000, status: "pending" }] });
      }
      if (path.includes("/hostel/allocations/alloc-2")) {
        return Promise.resolve({ id: "alloc-2", student_id: "u1", room: "B-202", status: "pending" });
      }
      return Promise.resolve([]);
    });
    post.mockImplementation((path: string) => {
      if (path.includes("/razorpay-order")) {
        return Promise.reject(new ApiError("Razorpay is not configured on this server.", 400));
      }
      return Promise.resolve({ ok: true });
    });

    render(<SagaDemoPage />);
    const payBtn = await screen.findByRole("button", { name: /pay & confirm/i });

    vi.useFakeTimers();
    fireEvent.click(payBtn);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });

    expect(screen.getByRole("status")).toHaveTextContent(/timed out/i);
  });
});
