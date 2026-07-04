// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

const router = { replace: vi.fn(), push: vi.fn(), prefetch: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router, usePathname: () => "/" }));

const get = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: { ...actual.api, get: (...args: unknown[]) => get(...args) } };
});

import DriverDashboard from "./page";
import { setToken } from "@/lib/auth";

function driverToken(): string {
  const payload = Buffer.from(
    JSON.stringify({ sub: "d1", role: "driver", tenant: "acme" }),
  ).toString("base64url");
  return `h.${payload}.s`;
}

const SCHEDULE = {
  id: "sch-1",
  route: { id: "r-1", name: "North Loop", start_point: "Gate A", end_point: "Hostel" },
  bus_no: "BUS-01",
  driver_id: "d1",
  departure_time: "08:00",
  capacity: 40,
  booked_count: 12,
};

describe("DriverDashboard", () => {
  beforeEach(() => {
    get.mockReset();
    window.localStorage.clear();
    setToken(driverToken());
  });

  it("renders my schedules", async () => {
    get.mockImplementation((path: string) => {
      if (path.includes("/schedules/mine")) {
        return Promise.resolve({ results: [SCHEDULE], count: 1 });
      }
      return Promise.resolve({ results: [], count: 0 });
    });

    render(<DriverDashboard />);

    expect(await screen.findByText("North Loop")).toBeInTheDocument();
    expect(screen.getByText("BUS-01")).toBeInTheDocument();
  });

  it("loads passengers when View passengers is clicked", async () => {
    get.mockImplementation((path: string) => {
      if (path.includes("/schedules/mine")) {
        return Promise.resolve({ results: [SCHEDULE], count: 1 });
      }
      if (path.includes("/bookings")) {
        return Promise.resolve({
          results: [{ id: "bk-1", schedule_id: "sch-1", student_id: "stu-5", seat_no: 7, status: "confirmed" }],
          count: 1,
        });
      }
      return Promise.resolve({ results: [], count: 0 });
    });

    render(<DriverDashboard />);
    await screen.findByText("North Loop");

    fireEvent.click(screen.getByRole("button", { name: "View passengers" }));

    expect(await screen.findByText("stu-5")).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("/api/v1/transport/schedules/sch-1/bookings");
  });
});
