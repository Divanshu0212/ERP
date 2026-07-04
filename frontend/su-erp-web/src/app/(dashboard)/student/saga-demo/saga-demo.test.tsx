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

import SagaDemoPage from "./page";
import { setToken } from "@/lib/auth";

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
    window.localStorage.clear();
    setToken(studentToken());
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("pays a pending allocation, polls, and flips it to confirmed", async () => {
    // allocation status is controlled by this variable; the polling GET reads it.
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
    post.mockResolvedValue({ ok: true });

    render(<SagaDemoPage />);

    const payBtn = await screen.findByRole("button", { name: /pay & confirm/i });
    expect(screen.getByText("Pending")).toBeInTheDocument();

    // Use fake timers for the polling phase only.
    vi.useFakeTimers();
    fireEvent.click(payBtn);

    // Pay POST + first immediate poll resolve.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(post).toHaveBeenCalledWith(
      "/api/v1/finance/pay",
      expect.objectContaining({ allocation_id: "alloc-1", invoice_id: "inv-1" }),
    );
    expect(screen.getByRole("status")).toHaveTextContent(/waiting for confirmation/i);

    // Saga confirms; the next 2s poll should pick it up.
    allocStatus = "confirmed";
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(screen.getByRole("status")).toHaveTextContent(/confirmed by the saga/i);
    // Pending list reloaded (allocation dropped off) -> empty state.
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
        // never confirms
        return Promise.resolve({ id: "alloc-2", student_id: "u1", room: "B-202", status: "pending" });
      }
      return Promise.resolve([]);
    });
    post.mockResolvedValue({ ok: true });

    render(<SagaDemoPage />);
    const payBtn = await screen.findByRole("button", { name: /pay & confirm/i });

    vi.useFakeTimers();
    fireEvent.click(payBtn);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    // Advance past the 10s timeout.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });

    expect(screen.getByRole("status")).toHaveTextContent(/timed out/i);
  });
});
