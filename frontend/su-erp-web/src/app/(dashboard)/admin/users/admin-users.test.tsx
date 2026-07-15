// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";

const router = { replace: vi.fn(), push: vi.fn(), prefetch: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router, usePathname: () => "/admin/users" }));

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

import AdminUsersPage from "./page";
import { setToken } from "@/lib/auth";

function adminToken(): string {
  const payload = Buffer.from(
    JSON.stringify({ sub: "a1", role: "admin", tenant: "acme" }),
  ).toString("base64url");
  return `h.${payload}.s`;
}

const USERS = [
  { user_code: "STU-1", email: "stu1@example.com", role: "student", is_active: true, date_joined: "2026-01-01T00:00:00Z" },
  { user_code: "STU-2", email: "stu2@example.com", role: "student", is_active: true, date_joined: "2026-01-02T00:00:00Z" },
];

function defaultGet(path: string) {
  if (path.includes("/auth/institution")) return Promise.resolve({ id: "i1", slug: "acme", name: "Acme" });
  if (path.includes("/auth/me")) return Promise.resolve({ email: "admin@acme.edu" });
  if (path.includes("/auth/users")) return Promise.resolve({ results: USERS, count: 2, page: 1, num_pages: 1 });
  return Promise.resolve({ items: [], total: 0 });
}

describe("AdminUsersPage", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    get.mockImplementation(defaultGet);
    window.localStorage.clear();
    setToken(adminToken());
  });

  it("lists users and bulk-deletes selected rows", async () => {
    post.mockResolvedValueOnce({
      deactivated: [{ user_code: "STU-1", email: "stu1@example.com" }],
      failed: [],
    });

    render(<AdminUsersPage />);
    await screen.findByText("stu1@example.com");
    await screen.findByText("stu2@example.com");

    const row1 = screen.getByText("stu1@example.com").closest("tr")!;
    fireEvent.click(within(row1).getByRole("checkbox"));

    fireEvent.click(screen.getByRole("button", { name: /delete selected/i }));
    fireEvent.click(await screen.findByRole("button", { name: /confirm/i }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/auth/users/bulk-delete/", {
        user_codes: ["STU-1"],
      }),
    );
    expect(await screen.findByText(/1 user\(s\) deactivated/i)).toBeInTheDocument();
  });

  it("disables the delete button until a row is selected", async () => {
    render(<AdminUsersPage />);
    await screen.findByText("stu1@example.com");
    expect(screen.getByRole("button", { name: /delete selected/i })).toBeDisabled();
  });

  it("refetches without the is_active filter when 'Include inactive users' is checked", async () => {
    render(<AdminUsersPage />);
    await screen.findByText("stu1@example.com");

    const initialCalls = get.mock.calls.length;

    fireEvent.click(screen.getByRole("checkbox", { name: /include inactive users/i }));

    await waitFor(() => expect(get.mock.calls.length).toBeGreaterThan(initialCalls));

    const usersCalls = get.mock.calls
      .map((args) => args[0] as string)
      .filter((path) => path.includes("/auth/users"));
    expect(usersCalls.length).toBeGreaterThanOrEqual(2);
    expect(usersCalls[usersCalls.length - 1]).not.toContain("is_active=true");
  });
});
