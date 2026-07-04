// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// Stable router: useAuthGuard lists `router` in an effect dep array, so a fresh
// object per call would re-run the effect and loop forever.
const router = { replace: vi.fn(), push: vi.fn(), prefetch: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router, usePathname: () => "/" }));

const get = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: { ...actual.api, get: (...args: unknown[]) => get(...args) } };
});

import StudentDashboard from "./page";
import { setToken } from "@/lib/auth";

function studentToken(): string {
  const payload = Buffer.from(
    JSON.stringify({ sub: "u1", role: "student", tenant: "acme" }),
  ).toString("base64url");
  return `h.${payload}.s`;
}

describe("StudentDashboard", () => {
  beforeEach(() => {
    get.mockReset();
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
});
