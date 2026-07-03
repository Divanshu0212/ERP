// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ApiError } from "@/lib/api";

// --- Mocks -----------------------------------------------------------------

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn(), prefetch: vi.fn() }),
}));

const post = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: { ...actual.api, post: (...args: unknown[]) => post(...args) } };
});

import LoginPage from "./page";

// A student JWT: header.{ sub, role:"student", tenant }.sig
function studentToken(): string {
  const payload = Buffer.from(
    JSON.stringify({ sub: "u1", role: "student", tenant: "acme" }),
  ).toString("base64url");
  return `h.${payload}.s`;
}

async function submitLogin() {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText(/email/i), "stu@acme.edu");
  await user.type(screen.getByLabelText(/password/i), "secret");
  await user.click(screen.getByRole("button", { name: /sign in/i }));
}

// --- Tests -----------------------------------------------------------------

describe("LoginPage", () => {
  beforeEach(() => {
    replace.mockReset();
    post.mockReset();
    window.localStorage.clear();
  });

  it("redirects to the student dashboard on successful login", async () => {
    post.mockResolvedValue({
      access_token: studentToken(),
      refresh_token: "refresh",
      user: { id: "u1", email: "stu@acme.edu", role: "student", tenant_id: "acme" },
    });

    render(<LoginPage />);
    await submitLogin();

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/student"));
    expect(post).toHaveBeenCalledWith("/api/v1/auth/login", {
      email: "stu@acme.edu",
      password: "secret",
    });
    expect(window.localStorage.getItem("access_token")).toBe(studentToken());
  });

  it("displays the envelope error message on failed login", async () => {
    post.mockRejectedValue(new ApiError("Invalid credentials", 401));

    render(<LoginPage />);
    await submitLogin();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Invalid credentials");
    expect(replace).not.toHaveBeenCalled();
  });
});
