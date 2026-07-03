// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// Stable router: useAuthGuard lists `router` in an effect dep array, so a fresh
// object per call would re-run the effect and loop forever.
const router = { replace: vi.fn(), push: vi.fn(), prefetch: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const get = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: { ...actual.api, get: (...args: unknown[]) => get(...args) } };
});

import AdminDashboard from "./page";
import { setToken } from "@/lib/auth";

function adminToken(): string {
  const payload = Buffer.from(
    JSON.stringify({ sub: "a1", role: "admin", tenant: "acme" }),
  ).toString("base64url");
  return `h.${payload}.s`;
}

describe("AdminDashboard", () => {
  beforeEach(() => {
    get.mockReset();
    window.localStorage.clear();
    setToken(adminToken());
  });

  it("renders cross-service counts from each service total", async () => {
    get.mockImplementation((path: string) => {
      if (path.includes("/users")) return Promise.resolve({ items: [{}], total: 42 });
      if (path.includes("/finance/invoices"))
        return Promise.resolve({ items: [{}], total: 156 });
      if (path.includes("/hostel/allocations"))
        return Promise.resolve({ items: [{}], total: 30 });
      if (path.includes("/grievance")) return Promise.resolve({ items: [{}], total: 7 });
      return Promise.resolve({ items: [], total: 0 });
    });

    render(<AdminDashboard />);

    expect(await screen.findByText("42")).toBeInTheDocument();
    expect(screen.getByText("156")).toBeInTheDocument();
    expect(screen.getByText("30")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("Users")).toBeInTheDocument();
    expect(screen.getByText("Invoices")).toBeInTheDocument();
  });

  it("shows a per-card error when one service fails", async () => {
    const { ApiError } = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
    get.mockImplementation((path: string) => {
      if (path.includes("/grievance"))
        return Promise.reject(new ApiError("grievance down", 503));
      return Promise.resolve({ items: [{}], total: 5 });
    });

    render(<AdminDashboard />);

    expect(await screen.findByText("grievance down")).toBeInTheDocument();
    // Other cards still render their counts.
    expect(screen.getAllByText("5").length).toBeGreaterThan(0);
  });
});
