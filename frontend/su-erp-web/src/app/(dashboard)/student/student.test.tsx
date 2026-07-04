// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// Stable router: useAuthGuard lists `router` in an effect dep array, so a fresh
// object per call would re-run the effect and loop forever.
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

// window.Razorpay is absent under jsdom — mock the checkout helper so tests can
// drive onSuccess/onDismiss without loading the real script.
const openRazorpayCheckout = vi.fn();
vi.mock("@/lib/razorpay", () => ({
  openRazorpayCheckout: (...args: unknown[]) => openRazorpayCheckout(...args),
  toPaise: (amount: number | string) =>
    Math.round(parseFloat(String(amount)) * 100),
}));

import StudentDashboard from "./page";
import { setToken } from "@/lib/auth";
import { ApiError } from "@/lib/api";

function invoicesOnlyGet(items: unknown[]) {
  return (path: string) => {
    if (path.includes("/finance/invoices")) return Promise.resolve({ items, total: items.length });
    if (path.includes("/notify/inbox")) return Promise.resolve({ items: [], total: 0 });
    return Promise.resolve([]);
  };
}

const pendingInvoice = {
  id: "inv-1",
  amount: 5000,
  status: "pending",
  purpose: "Hostel Fee",
  created_at: "2026-07-01T10:00:00Z",
};

function studentToken(): string {
  const payload = Buffer.from(
    JSON.stringify({ sub: "u1", role: "student", tenant: "acme" }),
  ).toString("base64url");
  return `h.${payload}.s`;
}

describe("StudentDashboard", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    openRazorpayCheckout.mockReset();
    window.localStorage.clear();
    setToken(studentToken());
  });

  it("renders invoices and notifications from the gateway", async () => {
    get.mockImplementation((path: string) => {
      if (path.includes("/finance/invoices")) {
        return Promise.resolve({
          items: [
            {
              id: "inv-1",
              amount: 5000,
              status: "pending",
              purpose: "Hostel Fee",
              created_at: "2026-07-01T10:00:00Z",
            },
            {
              id: "inv-2",
              amount: 1200,
              status: "paid",
              purpose: "Library Fine",
              created_at: "2026-07-02T10:00:00Z",
            },
          ],
          total: 2,
        });
      }
      if (path.includes("/notify/inbox")) {
        return Promise.resolve({
          items: [
            {
              id: "n-1",
              title: "Welcome",
              body: "Your account is ready.",
              created_at: "2026-07-01T09:00:00Z",
            },
          ],
          total: 1,
        });
      }
      return Promise.resolve([]);
    });

    render(<StudentDashboard />);

    expect(await screen.findByText("Hostel Fee")).toBeInTheDocument();
    expect(screen.getByText("Library Fine")).toBeInTheDocument();
    expect(await screen.findByText("Welcome")).toBeInTheDocument();
    expect(screen.getByText("Your account is ready.")).toBeInTheDocument();

    // Unpaid invoice has an enabled "Pay" button; paid one is disabled ("Paid").
    const payBtn = screen.getByRole("button", { name: /^pay$/i }) as HTMLButtonElement;
    expect(payBtn.disabled).toBe(false);
    const paidBtn = screen.getByRole("button", { name: /^paid$/i }) as HTMLButtonElement;
    expect(paidBtn.disabled).toBe(true);

    expect(screen.getByRole("button", { name: /raise grievance/i })).toBeInTheDocument();
  });

  it("shows an error state when invoices fail to load", async () => {
    const { ApiError } = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
    get.mockImplementation((path: string) => {
      if (path.includes("/finance/invoices")) {
        return Promise.reject(new ApiError("finance down", 503));
      }
      return Promise.resolve({ items: [], total: 0 });
    });

    render(<StudentDashboard />);

    expect(await screen.findByText("finance down")).toBeInTheDocument();
  });

  it("pays an invoice via the Razorpay widget and verifies the payment", async () => {
    get.mockImplementation(invoicesOnlyGet([pendingInvoice]));
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
    openRazorpayCheckout.mockImplementation((opts: { onSuccess: (r: unknown) => void }) => {
      opts.onSuccess({
        razorpay_order_id: "order_abc",
        razorpay_payment_id: "pay_abc",
        razorpay_signature: "sig_abc",
      });
      return Promise.resolve();
    });

    render(<StudentDashboard />);
    fireEvent.click(await screen.findByRole("button", { name: /^pay$/i }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/api/v1/finance/pay",
        expect.objectContaining({
          invoice_id: "inv-1",
          idempotency_key: expect.any(String),
          razorpay_order_id: "order_abc",
          razorpay_payment_id: "pay_abc",
          razorpay_signature: "sig_abc",
        }),
      ),
    );
    expect(await screen.findByText("Payment successful.")).toBeInTheDocument();
  });

  it("falls back to the simulated direct-pay path when Razorpay is not configured", async () => {
    get.mockImplementation(invoicesOnlyGet([pendingInvoice]));
    post.mockImplementation((path: string) => {
      if (path.includes("/razorpay-order")) {
        return Promise.reject(new ApiError("Razorpay is not configured on this server.", 400));
      }
      return Promise.resolve({ ok: true });
    });

    render(<StudentDashboard />);
    fireEvent.click(await screen.findByRole("button", { name: /^pay$/i }));

    await waitFor(() => {
      const payCall = post.mock.calls.find((c) => c[0] === "/api/v1/finance/pay");
      expect(payCall).toBeTruthy();
    });
    expect(openRazorpayCheckout).not.toHaveBeenCalled();
    const payCall = post.mock.calls.find((c) => c[0] === "/api/v1/finance/pay")!;
    expect(payCall[1]).toMatchObject({ invoice_id: "inv-1", idempotency_key: expect.any(String) });
    expect(payCall[1]).not.toHaveProperty("razorpay_order_id");
    expect(await screen.findByText("Payment successful.")).toBeInTheDocument();
  });
});
