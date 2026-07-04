// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, act, fireEvent } from "@testing-library/react";

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

import EscalationDemoPage from "./page";
import { setToken } from "@/lib/auth";

function studentToken(): string {
  const payload = Buffer.from(
    JSON.stringify({ sub: "u1", role: "student", tenant: "acme" }),
  ).toString("base64url");
  return `h.${payload}.s`;
}

describe("EscalationDemoPage", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    window.localStorage.clear();
    setToken(studentToken());
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("submits a grievance and shows urgency/sentiment after scoring", async () => {
    post.mockResolvedValue({
      id: "grv-1",
      description: "the warden is threatening me, this is ragging",
      status: "open",
      urgency: null,
      sentiment_score: null,
    });

    // Unscored on first polls, scored later.
    let scored = false;
    get.mockImplementation((path: string) => {
      if (path.includes("/grievance/grv-1")) {
        return Promise.resolve(
          scored
            ? {
                id: "grv-1",
                description: "x",
                status: "escalated",
                urgency: "critical",
                sentiment_score: -0.87,
              }
            : {
                id: "grv-1",
                description: "x",
                status: "open",
                urgency: null,
                sentiment_score: null,
              },
        );
      }
      return Promise.resolve([]);
    });

    render(<EscalationDemoPage />);

    // Pre-filled urgent text.
    const textarea = (await screen.findByLabelText(/grievance description/i)) as HTMLTextAreaElement;
    expect(textarea.value).toMatch(/ragging/i);

    const submitBtn = screen.getByRole("button", { name: /submit grievance/i });

    vi.useFakeTimers();
    fireEvent.click(submitBtn);

    // Creation POST + first immediate poll (still unscored).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(post).toHaveBeenCalledWith("/api/v1/grievance", expect.objectContaining({
      description: expect.stringMatching(/ragging/i),
    }));
    expect(screen.getByRole("status")).toHaveTextContent(/waiting for the ai service/i);

    // Score becomes available; next 1s poll picks it up.
    scored = true;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(screen.getByText("critical")).toBeInTheDocument();
    expect(screen.getByText(/negative/i)).toBeInTheDocument();
    expect(screen.getByText(/-0\.87/)).toBeInTheDocument();
  });

  it("times out when scoring never arrives", async () => {
    post.mockResolvedValue({
      id: "grv-2",
      description: "x",
      status: "open",
      urgency: null,
      sentiment_score: null,
    });
    get.mockImplementation((path: string) => {
      if (path.includes("/grievance/grv-2")) {
        return Promise.resolve({
          id: "grv-2",
          description: "x",
          status: "open",
          urgency: null,
          sentiment_score: null,
        });
      }
      return Promise.resolve([]);
    });

    render(<EscalationDemoPage />);
    const submitBtn = await screen.findByRole("button", { name: /submit grievance/i });

    vi.useFakeTimers();
    fireEvent.click(submitBtn);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    // Past the 5s timeout.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(screen.getByRole("alert")).toHaveTextContent(/timed out/i);
  });
});
