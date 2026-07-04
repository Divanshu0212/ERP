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

import AdminDashboard from "./page";
import { ApiError } from "@/lib/api";
import { setToken } from "@/lib/auth";

function adminToken(): string {
  const payload = Buffer.from(
    JSON.stringify({ sub: "a1", role: "admin", tenant: "acme" }),
  ).toString("base64url");
  return `h.${payload}.s`;
}

const INSTITUTION = {
  id: "inst-1",
  slug: "acme-university",
  name: "Acme University",
  is_active: true,
  created_at: "2024-01-01T00:00:00Z",
};

function userList(extra: Record<string, unknown>[] = []) {
  const base = {
    id: "u1",
    email: "alice@acme.edu",
    role: "student",
    is_active: true,
    date_joined: "2024-05-01T00:00:00Z",
  };
  return { results: [base, ...extra], count: 1 + extra.length };
}

// Default get: institution, user list, and cross-service counts.
function defaultGet(path: string) {
  if (path.includes("/auth/institution")) return Promise.resolve(INSTITUTION);
  if (path.includes("/auth/users")) return Promise.resolve(userList());
  if (path.includes("/finance/invoices")) return Promise.resolve({ items: [{}], total: 156 });
  if (path.includes("/hostel/allocations")) return Promise.resolve({ items: [{}], total: 30 });
  if (path.includes("/grievance")) return Promise.resolve({ items: [{}], total: 7 });
  if (path.includes("/hostel/blocks")) {
    return Promise.resolve({ items: [{ id: "blk-1", name: "Block A", gender_type: "M", warden_id: "w1" }], total: 1 });
  }
  if (path.includes("/hostel/rooms")) {
    return Promise.resolve({
      items: [{ id: "rm-1", block_name: "Block A", room_no: "101", capacity: 2, occupied_count: 1 }],
      total: 1,
    });
  }
  return Promise.resolve({ items: [], total: 0 });
}

describe("AdminDashboard", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    window.localStorage.clear();
    setToken(adminToken());
  });

  it("renders the institution header, a user row, and stat counts", async () => {
    get.mockImplementation(defaultGet);

    render(<AdminDashboard />);

    // Institution header.
    expect(await screen.findByText("Acme University")).toBeInTheDocument();
    expect(screen.getByText("acme-university")).toBeInTheDocument();

    // A user row from the roster.
    expect(await screen.findByText("alice@acme.edu")).toBeInTheDocument();

    // Stat cards: users total (from the same envelope) + a cross-service count.
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(await screen.findByText("156")).toBeInTheDocument();
  });

  it("creates a user, refetches the list, and shows a success message", async () => {
    let created = false;
    get.mockImplementation((path: string) => {
      if (path.includes("/auth/users")) {
        return Promise.resolve(
          created ? userList([{ id: "u2", email: "bob@acme.edu", role: "faculty", is_active: true, date_joined: "2024-06-01T00:00:00Z" }]) : userList(),
        );
      }
      return defaultGet(path);
    });
    post.mockImplementation(() => {
      created = true;
      return Promise.resolve({ id: "u2", email: "bob@acme.edu", role: "faculty" });
    });

    render(<AdminDashboard />);

    await screen.findByText("alice@acme.edu");

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "bob@acme.edu" } });
    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "faculty" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "s3cretpass" } });
    fireEvent.click(screen.getByRole("button", { name: "Add User" }));

    // Posted with the form payload.
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/auth/users", {
        email: "bob@acme.edu",
        role: "faculty",
        password: "s3cretpass",
      }),
    );

    // List refetched -> the new user appears; success message shows.
    expect(await screen.findByText("bob@acme.edu")).toBeInTheDocument();
    expect(screen.getByText(/Created user bob@acme.edu/)).toBeInTheDocument();
  });

  it("creates an invoice and shows a success message", async () => {
    get.mockImplementation(defaultGet);
    post.mockResolvedValue({ id: "inv-1", status: "pending" });

    render(<AdminDashboard />);
    await screen.findByText("alice@acme.edu");

    fireEvent.change(screen.getByLabelText("Student email"), { target: { value: "alice@acme.edu" } });
    fireEvent.change(screen.getByLabelText("Amount"), { target: { value: "500" } });
    fireEvent.change(screen.getByLabelText("Purpose"), { target: { value: "Hostel fee" } });
    fireEvent.click(screen.getByRole("button", { name: "Create invoice" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/finance/invoices", {
        student_id: "u1",
        amount: "500",
        purpose: "Hostel fee",
      }),
    );
    expect(await screen.findByText("Invoice created.")).toBeInTheDocument();
  });

  it("shows the envelope error when creating a user fails", async () => {
    get.mockImplementation(defaultGet);
    post.mockRejectedValue(new ApiError("User with this email already exists.", 400));

    render(<AdminDashboard />);
    await screen.findByText("alice@acme.edu");

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "alice@acme.edu" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "s3cretpass" } });
    fireEvent.click(screen.getByRole("button", { name: "Add User" }));

    expect(
      await screen.findByText("User with this email already exists."),
    ).toBeInTheDocument();
    // No crash: the roster is still on screen.
    expect(screen.getByText("alice@acme.edu")).toBeInTheDocument();
  });

  it("renders hostel blocks and rooms", async () => {
    get.mockImplementation(defaultGet);

    render(<AdminDashboard />);

    expect((await screen.findAllByText("Block A"))[0]).toBeInTheDocument();
    expect(await screen.findByText("101")).toBeInTheDocument();
  });

  it("creates a block by warden email", async () => {
    get.mockImplementation(defaultGet);
    post.mockResolvedValue({ id: "blk-2", name: "Block B", gender_type: "F", warden_id: "w2" });

    render(<AdminDashboard />);
    await screen.findAllByText("Block A");

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Block B" } });
    fireEvent.change(screen.getByLabelText("Gender type"), { target: { value: "F" } });
    fireEvent.change(screen.getByLabelText("Warden email"), { target: { value: "warden@acme.edu" } });
    fireEvent.click(screen.getByRole("button", { name: "Create block" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/hostel/blocks", {
        name: "Block B",
        gender_type: "F",
        warden_email: "warden@acme.edu",
      }),
    );
    expect(await screen.findByText("Block created.")).toBeInTheDocument();
  });

  it("creates a room under a block", async () => {
    get.mockImplementation(defaultGet);
    post.mockResolvedValue({ id: "rm-2", block_name: "Block A", room_no: "202", capacity: 2, occupied_count: 0 });

    render(<AdminDashboard />);
    await screen.findAllByText("Block A");

    fireEvent.change(screen.getByLabelText("Block"), { target: { value: "blk-1" } });
    fireEvent.change(screen.getByLabelText("Room number"), { target: { value: "202" } });
    fireEvent.change(screen.getByLabelText("Capacity"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Create room" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/hostel/rooms", {
        block_id: "blk-1",
        room_no: "202",
        capacity: 2,
      }),
    );
    expect(await screen.findByText("Room created.")).toBeInTheDocument();
  });
});
