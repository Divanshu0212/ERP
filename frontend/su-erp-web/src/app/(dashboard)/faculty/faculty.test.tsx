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

import FacultyDashboard from "./page";
import { setToken } from "@/lib/auth";

function facultyToken(): string {
  const payload = Buffer.from(
    JSON.stringify({ sub: "f1", role: "faculty", tenant: "acme" }),
  ).toString("base64url");
  return `h.${payload}.s`;
}

function defaultGet(path: string) {
  if (path.includes("/attendance/records")) {
    return Promise.resolve({
      results: [
        { id: "att-1", student_id: "stu-7", course_id: "CS101", date: "2026-07-01", status: "present" },
      ],
      count: 1,
    });
  }
  if (path.includes("/exams/schedules")) {
    return Promise.resolve({
      results: [
        { id: "ex-1", course_id: "CS101", exam_date: "2026-07-10", room_no: "R-12", duration_minutes: 90 },
      ],
      count: 1,
    });
  }
  return Promise.resolve({ results: [], count: 0 });
}

describe("FacultyDashboard", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    window.localStorage.clear();
    setToken(facultyToken());
  });

  it("renders attendance records and exam schedules", async () => {
    get.mockImplementation(defaultGet);

    render(<FacultyDashboard />);

    expect(await screen.findByText("stu-7")).toBeInTheDocument();
    expect(screen.getByText("R-12")).toBeInTheDocument();
    expect(screen.getByText("90 min")).toBeInTheDocument();
  });

  it("marks attendance and refetches", async () => {
    get.mockImplementation(defaultGet);
    post.mockResolvedValue({ id: "att-2" });

    render(<FacultyDashboard />);
    await screen.findByText("stu-7");

    fireEvent.change(screen.getByLabelText("Student ID"), { target: { value: "stu-9" } });
    fireEvent.change(screen.getByLabelText("Course ID"), { target: { value: "CS102" } });
    fireEvent.change(screen.getByLabelText("Date"), { target: { value: "2026-07-02" } });
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "absent" } });
    fireEvent.click(screen.getByRole("button", { name: "Mark attendance" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/attendance/records", {
        student_id: "stu-9",
        course_id: "CS102",
        date: "2026-07-02",
        status: "absent",
      }),
    );
    expect(await screen.findByText("Attendance recorded.")).toBeInTheDocument();
  });

  it("creates an exam schedule", async () => {
    get.mockImplementation(defaultGet);
    post.mockResolvedValue({ id: "ex-2" });

    render(<FacultyDashboard />);
    await screen.findByText("R-12");

    fireEvent.change(screen.getByLabelText("Exam course ID"), { target: { value: "CS201" } });
    fireEvent.change(screen.getByLabelText("Exam date"), { target: { value: "2026-07-15" } });
    fireEvent.change(screen.getByLabelText("Room no"), { target: { value: "R-20" } });
    fireEvent.change(screen.getByLabelText("Duration (min)"), { target: { value: "120" } });
    fireEvent.click(screen.getByRole("button", { name: "Create schedule" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/exams/schedules", {
        course_id: "CS201",
        exam_date: "2026-07-15",
        room_no: "R-20",
        duration_minutes: 120,
      }),
    );
    expect(await screen.findByText("Exam schedule created.")).toBeInTheDocument();
  });
});
