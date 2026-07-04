// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// Stable router: useAuthGuard lists `router` in an effect dep array.
const router = { replace: vi.fn(), push: vi.fn(), prefetch: vi.fn() };
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/superadmin",
}));

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

import SuperadminPage from "./page";
import { ApiError } from "@/lib/api";
import { setToken } from "@/lib/auth";

function superToken(): string {
  const payload = Buffer.from(
    JSON.stringify({ sub: "s1", role: "superadmin", tenant: "platform" }),
  ).toString("base64url");
  return `h.${payload}.s`;
}

const PLATFORM = { id: "p1", slug: "platform", name: "Platform", is_active: true };

function institutions(extra: Record<string, unknown>[] = []) {
  const base = {
    id: "i1",
    slug: "riverside-tech",
    name: "Riverside Tech",
    is_active: true,
    created_at: "2024-01-01T00:00:00Z",
  };
  return { results: [base, ...extra], count: 1 + extra.length };
}

function defaultGet(path: string) {
  if (path.includes("/auth/institution")) {
    // The shell fetches /auth/institution (singular); the page fetches
    // /auth/institutions (plural).
    if (path.includes("/auth/institutions")) return Promise.resolve(institutions());
    return Promise.resolve(PLATFORM);
  }
  return Promise.resolve({ results: [], count: 0 });
}

describe("SuperadminPage", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    window.localStorage.clear();
    setToken(superToken());
  });

  it("lists institutions", async () => {
    get.mockImplementation(defaultGet);
    render(<SuperadminPage />);
    expect(await screen.findByText("riverside-tech")).toBeInTheDocument();
  });

  it("creates an institution, refetches, and shows success", async () => {
    let created = false;
    get.mockImplementation((path: string) => {
      if (path.includes("/auth/institutions")) {
        return Promise.resolve(
          created
            ? institutions([
                {
                  id: "i2",
                  slug: "acme-college",
                  name: "Acme College",
                  is_active: true,
                  created_at: "2024-02-01T00:00:00Z",
                },
              ])
            : institutions(),
        );
      }
      return defaultGet(path);
    });
    post.mockImplementation(() => {
      created = true;
      return Promise.resolve({ id: "i2", slug: "acme-college", name: "Acme College", is_active: true });
    });

    render(<SuperadminPage />);
    await screen.findByText("riverside-tech");

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Acme College" } });
    fireEvent.click(screen.getByRole("button", { name: "Create institution" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/auth/institutions", {
        slug: "acme-college",
        name: "Acme College",
      }),
    );
    expect(await screen.findByText("acme-college")).toBeInTheDocument();
    expect(screen.getByText(/Created Acme College/)).toBeInTheDocument();
  });

  it("adds an admin to an institution", async () => {
    get.mockImplementation(defaultGet);
    post.mockResolvedValue({
      id: "a1",
      email: "admin@riverside.edu",
      role: "admin",
      institution_slug: "riverside-tech",
    });

    render(<SuperadminPage />);
    await screen.findByText("riverside-tech");

    fireEvent.change(screen.getByLabelText("Institution"), {
      target: { value: "riverside-tech" },
    });
    fireEvent.change(screen.getByLabelText("Admin email"), {
      target: { value: "admin@riverside.edu" },
    });
    fireEvent.change(screen.getByLabelText("Temporary password"), {
      target: { value: "s3cretpass" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add admin" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/auth/admins", {
        institution_slug: "riverside-tech",
        email: "admin@riverside.edu",
        password: "s3cretpass",
      }),
    );
    expect(await screen.findByText(/Admin admin@riverside.edu added/)).toBeInTheDocument();
  });

  it("shows the envelope error when creating an institution fails", async () => {
    get.mockImplementation(defaultGet);
    post.mockRejectedValue(new ApiError("Institution with this slug already exists.", 400));

    render(<SuperadminPage />);
    await screen.findByText("riverside-tech");

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Riverside Tech" } });
    fireEvent.click(screen.getByRole("button", { name: "Create institution" }));

    expect(
      await screen.findByText("Institution with this slug already exists."),
    ).toBeInTheDocument();
  });
});
