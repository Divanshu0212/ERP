// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
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

import { LiveSessionSection } from "./LiveSessionSection";
import { setToken } from "@/lib/auth";

function facultyToken(): string {
  const payload = Buffer.from(
    JSON.stringify({ sub: "FAC-001", role: "faculty", tenant: "acme" }),
  ).toString("base64url");
  return `h.${payload}.s`;
}

const OPEN_SESSION = {
  id: "sess-1",
  course_code: "CS101",
  faculty_id: "FAC-001",
  lat: "12.971599",
  lng: "77.594566",
  radius_m: 50,
  opened_at: "2026-08-03T09:00:00Z",
  closed_at: null,
};

function defaultGet(path: string) {
  if (path.includes("/sessions/sess-1/code")) {
    return Promise.resolve({ code: "482913", rotates_in: 15 });
  }
  if (path.includes("/sessions/sess-1/marks")) {
    return Promise.resolve([
      {
        id: "m1",
        session: "sess-1",
        student_user_code: "STU-001",
        distance_m: 12.4,
        mock_location: false,
        marked_at: "2026-08-03T09:01:00Z",
      },
    ]);
  }
  if (path.includes("/attendance/sessions")) {
    return Promise.resolve({ results: [OPEN_SESSION], count: 1 });
  }
  return Promise.resolve({ results: [], count: 0 });
}

describe("LiveSessionSection", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    window.localStorage.clear();
    setToken(facultyToken());
    // The console polls the code and roster; fake timers keep that
    // deterministic instead of racing a real 15-second rotation.
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows the rotating code and the roster for a running session", async () => {
    get.mockImplementation(defaultGet);

    render(<LiveSessionSection />);

    expect(await screen.findByText("482913")).toBeInTheDocument();
    expect(await screen.findByText("STU-001")).toBeInTheDocument();
  });

  it("opens a session pinned to the room's coordinates", async () => {
    // Starts idle: the open form only exists when no class is running.
    get.mockImplementation(() => Promise.resolve({ results: [], count: 0 }));
    post.mockResolvedValue(OPEN_SESSION);

    render(<LiveSessionSection />);
    await screen.findByText("No class is running right now.");

    fireEvent.change(screen.getByLabelText("Course code"), { target: { value: "CS202" } });
    fireEvent.change(screen.getByLabelText("Latitude"), { target: { value: "12.9" } });
    fireEvent.change(screen.getByLabelText("Longitude"), { target: { value: "77.5" } });
    fireEvent.change(screen.getByLabelText("Radius (m)"), { target: { value: "40" } });
    fireEvent.click(screen.getByRole("button", { name: "Open session" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/attendance/sessions", {
        course_code: "CS202",
        lat: "12.9",
        lng: "77.5",
        radius_m: 40,
      }),
    );
  });

  it("closes a running session", async () => {
    get.mockImplementation(defaultGet);
    post.mockResolvedValue({ ...OPEN_SESSION, closed_at: "2026-08-03T10:00:00Z" });

    render(<LiveSessionSection />);
    await screen.findByText("482913");

    fireEvent.click(screen.getByRole("button", { name: "Close session" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/attendance/sessions/sess-1/close", {}),
    );
  });

  it("does not ask for a code when no session is running", async () => {
    get.mockImplementation((path: string) => {
      if (path.includes("/attendance/sessions")) {
        return Promise.resolve({ results: [], count: 0 });
      }
      return Promise.resolve({ results: [], count: 0 });
    });

    render(<LiveSessionSection />);

    expect(await screen.findByText("No class is running right now.")).toBeInTheDocument();
    expect(get).not.toHaveBeenCalledWith(expect.stringContaining("/code"));
  });
});
