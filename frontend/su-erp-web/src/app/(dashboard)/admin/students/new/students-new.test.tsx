// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// Stable router: useAuthGuard lists `router` in an effect dep array, so a fresh
// object per call would re-run the effect and loop forever.
const router = { replace: vi.fn(), push: vi.fn(), prefetch: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router, usePathname: () => "/admin/students/new" }));

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

import AddStudentsPage from "./page";
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
};

function defaultGet(path: string) {
  if (path.includes("/auth/institution")) return Promise.resolve(INSTITUTION);
  if (path.includes("/auth/me")) return Promise.resolve({ email: "admin@acme.edu" });
  return Promise.resolve({ items: [], total: 0 });
}

describe("AddStudentsPage", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    get.mockImplementation(defaultGet);
    window.localStorage.clear();
    setToken(adminToken());
  });

  describe("single-student form", () => {
    it("submits one row wrapped in a rows array", async () => {
      post.mockResolvedValueOnce({
        created: [{ row: 0, email: "new@example.com", user_code: "STU-1" }],
        failed: [],
      });

      render(<AddStudentsPage />);
      await screen.findByText("Add one student");

      fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "new@example.com" } });
      fireEvent.change(screen.getByLabelText(/user code/i), { target: { value: "STU-1" } });
      fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "s3cur3pass" } });
      fireEvent.change(screen.getByLabelText(/department/i), { target: { value: "CS" } });
      fireEvent.change(screen.getByLabelText(/batch/i), { target: { value: "2026" } });
      fireEvent.change(screen.getByLabelText(/semester/i), { target: { value: "1" } });
      fireEvent.click(screen.getByRole("button", { name: /add student/i }));

      await waitFor(() =>
        expect(post).toHaveBeenCalledWith("/api/v1/auth/users/bulk/", {
          rows: [expect.objectContaining({ email: "new@example.com", user_code: "STU-1" })],
        }),
      );
      expect(await screen.findByText(/Created new@example\.com\./i)).toBeInTheDocument();
    });
  });

  describe("bulk CSV upload", () => {
    function csvFile(contents: string) {
      return new File([contents], "students.csv", { type: "text/csv" });
    }

    it("parses a CSV and posts all rows, then renders per-row results", async () => {
      post.mockResolvedValueOnce({
        created: [{ row: 0, email: "a@example.com", user_code: "STU-A" }],
        failed: [{ row: 1, email: "b@example.com", error: "A user with this email already exists." }],
      });

      render(<AddStudentsPage />);
      await screen.findByText("Add one student");

      const csv = [
        "email,user_code,password,department,batch,semester",
        "a@example.com,STU-A,s3cur3pass,CS,2026,1",
        "b@example.com,STU-B,s3cur3pass,EE,2026,2",
      ].join("\n");

      const input = screen.getByLabelText(/csv file/i);
      fireEvent.change(input, { target: { files: [csvFile(csv)] } });

      await waitFor(() =>
        expect(post).toHaveBeenCalledWith("/api/v1/auth/users/bulk/", {
          rows: [
            expect.objectContaining({ email: "a@example.com", user_code: "STU-A" }),
            expect.objectContaining({ email: "b@example.com", user_code: "STU-B" }),
          ],
        }),
      );

      expect(await screen.findByText("a@example.com")).toBeInTheDocument();
      expect(await screen.findByText("b@example.com")).toBeInTheDocument();
      expect(screen.getByText(/already exists/i)).toBeInTheDocument();
    });

    it("rejects a CSV with the wrong header before making any request", async () => {
      render(<AddStudentsPage />);
      await screen.findByText("Add one student");

      const badCsv = "name,code\nJane,STU-1";
      const input = screen.getByLabelText(/csv file/i);
      fireEvent.change(input, { target: { files: [csvFile(badCsv)] } });

      expect(await screen.findByText(/unexpected header/i)).toBeInTheDocument();
      expect(post).not.toHaveBeenCalled();
    });
  });
});
