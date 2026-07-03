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

import WardenDashboard from "./page";
import { setToken } from "@/lib/auth";

function wardenToken(): string {
  const payload = Buffer.from(
    JSON.stringify({ sub: "w1", role: "warden", tenant: "acme" }),
  ).toString("base64url");
  return `h.${payload}.s`;
}

describe("WardenDashboard", () => {
  beforeEach(() => {
    get.mockReset();
    window.localStorage.clear();
    setToken(wardenToken());
  });

  it("renders pending allocations and escalated grievances", async () => {
    get.mockImplementation((path: string) => {
      if (path.includes("/hostel/allocations")) {
        return Promise.resolve({
          items: [{ id: "a-1", student_id: "stu-42", room: "B-204", status: "pending" }],
          total: 1,
        });
      }
      if (path.includes("/grievance")) {
        return Promise.resolve({
          items: [
            {
              id: "tkt-9",
              raised_by: "stu-42",
              status: "escalated",
              assigned_to: "w1",
            },
          ],
          total: 1,
        });
      }
      return Promise.resolve([]);
    });

    render(<WardenDashboard />);

    // Room is unique to the allocations table; student_id appears in both tables.
    expect(await screen.findByText("B-204")).toBeInTheDocument();
    expect(screen.getAllByText("stu-42").length).toBe(2);
    expect(await screen.findByText("tkt-9")).toBeInTheDocument();
    expect(screen.getByText("escalated")).toBeInTheDocument();
  });

  it("shows empty states when there is nothing to review", async () => {
    get.mockResolvedValue({ items: [], total: 0 });

    render(<WardenDashboard />);

    expect(await screen.findByText("No pending allocations.")).toBeInTheDocument();
    expect(await screen.findByText("No escalated grievances.")).toBeInTheDocument();
  });
});
