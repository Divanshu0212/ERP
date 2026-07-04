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
    post.mockReset();
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

  it("creates a hostel allocation", async () => {
    get.mockResolvedValue({ items: [], total: 0 });
    post.mockResolvedValue({ id: "a-2", status: "pending", room_id: "rm-1", student_id: "stu-1" });

    render(<WardenDashboard />);
    await screen.findByText("No pending allocations.");

    fireEvent.change(screen.getByLabelText("Room ID"), { target: { value: "rm-1" } });
    fireEvent.change(screen.getByLabelText("Student ID"), { target: { value: "stu-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Create allocation" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/hostel/allocate", {
        room_id: "rm-1",
        student_id: "stu-1",
      }),
    );
    expect(await screen.findByText("Allocation created.")).toBeInTheDocument();
  });
});
