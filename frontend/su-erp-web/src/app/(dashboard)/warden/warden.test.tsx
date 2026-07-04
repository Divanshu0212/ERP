// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// Stable router: useAuthGuard lists `router` in an effect dep array, so a fresh
// object per call would re-run the effect and loop forever.
const router = { replace: vi.fn(), push: vi.fn(), prefetch: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router, usePathname: () => "/" }));

const get = vi.fn();
const post = vi.fn();
const upload = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      ...actual.api,
      get: (...args: unknown[]) => get(...args),
      post: (...args: unknown[]) => post(...args),
      upload: (...args: unknown[]) => upload(...args),
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
    upload.mockReset();
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
    get.mockImplementation((path: string) => {
      if (path.includes("/hostel/rooms/available")) {
        return Promise.resolve({
          items: [{ id: "rm-1", block_name: "Block A", room_no: "101", capacity: 2, occupied_count: 0 }],
          total: 1,
        });
      }
      return Promise.resolve({ items: [], total: 0 });
    });
    post.mockResolvedValue({ id: "a-2", status: "pending", room_id: "rm-1", student_id: "stu-1" });

    render(<WardenDashboard />);
    await screen.findByText("No pending allocations.");

    fireEvent.change(screen.getByLabelText("Room"), { target: { value: "rm-1" } });
    fireEvent.change(screen.getByLabelText("Student email"), { target: { value: "student@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Create allocation" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/hostel/allocate", {
        room_id: "rm-1",
        student_email: "student@example.com",
      }),
    );
    expect(await screen.findByText("Allocation created.")).toBeInTheDocument();
  });

  it("uploads a bulk allocation file and shows the summary", async () => {
    get.mockResolvedValue({ items: [], total: 0 });
    upload.mockResolvedValue({ batch_id: "b1", total_rows: 3, success_count: 2, fail_count: 1 });

    render(<WardenDashboard />);
    await screen.findByText("No pending allocations.");

    const file = new File(["room_id,student_email\n"], "import.csv", { type: "text/csv" });
    const input = screen.getByLabelText("File") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));

    await waitFor(() =>
      expect(upload).toHaveBeenCalledWith("/api/v1/hostel/allocate/bulk", file),
    );
    expect(
      await screen.findByText(/2 succeeded, 1 failed out of 3/),
    ).toBeInTheDocument();
  });

  it("shows import logs and drills into a batch's rows", async () => {
    get.mockImplementation((path: string) => {
      if (path.includes("/import-logs/batch-1")) {
        return Promise.resolve({
          id: "batch-1",
          filename: "import.csv",
          total_rows: 1,
          success_count: 0,
          fail_count: 1,
          created_at: "2026-01-01T00:00:00Z",
          rows: [
            {
              row_number: 1,
              room_id_raw: "rm-9",
              student_email_raw: "bad@example.com",
              status: "failed",
              error_message: "No user found with email bad@example.com.",
              allocation_id: null,
            },
          ],
        });
      }
      if (path.includes("/import-logs")) {
        return Promise.resolve({
          items: [
            {
              id: "batch-1",
              filename: "import.csv",
              total_rows: 1,
              success_count: 0,
              fail_count: 1,
              created_at: "2026-01-01T00:00:00Z",
            },
          ],
          total: 1,
        });
      }
      return Promise.resolve({ items: [], total: 0 });
    });

    render(<WardenDashboard />);

    expect(await screen.findByText("import.csv")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View" }));

    expect(
      await screen.findByText("No user found with email bad@example.com."),
    ).toBeInTheDocument();
  });
});
