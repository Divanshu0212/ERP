"use client";

import { useCallback, useEffect, useState } from "react";

import { DashboardShell } from "@/components/DashboardShell";
import { DataPanel } from "@/components/DataPanel";
import { api, ApiError } from "@/lib/api";
import { listItems } from "@/lib/paginate";
import { Button } from "@/components/ui/Button";
import { StatusPill } from "@/components/ui/StatusPill";
import { Table, TBody, TD, TH, THead, HeaderRow, Row } from "@/components/ui/Table";

interface Schedule {
  id: string;
  route: { id: string; name: string; start_point: string; end_point: string };
  bus_no: string;
  driver_id: string;
  departure_time: string;
  capacity: number;
  booked_count: number;
}

interface Booking {
  id: string;
  schedule_id: string;
  student_id: string;
  seat_no: number | string;
  status: string;
  created_at: string;
}

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return e instanceof Error ? e.message : "Something went wrong.";
}

function DriverContent() {
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [selected, setSelected] = useState<Schedule | null>(null);
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [bookingsLoading, setBookingsLoading] = useState(false);
  const [bookingsError, setBookingsError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await api.get("/api/v1/transport/schedules/mine");
      setSchedules(listItems<Schedule>(data));
    } catch (e) {
      setLoadError(errMsg(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const viewPassengers = useCallback(async (schedule: Schedule) => {
    setSelected(schedule);
    setBookingsLoading(true);
    setBookingsError(null);
    setBookings([]);
    try {
      const data = await api.get(`/api/v1/transport/schedules/${schedule.id}/bookings`);
      setBookings(listItems<Booking>(data));
    } catch (e) {
      setBookingsError(errMsg(e));
    } finally {
      setBookingsLoading(false);
    }
  }, []);

  return (
    <div className="space-y-6">
      <DataPanel
        title="My schedules"
        loading={loading}
        error={loadError}
        isEmpty={schedules.length === 0}
        emptyLabel="No schedules assigned."
      >
        <Table>
          <THead>
            <HeaderRow>
              <TH>Route</TH>
              <TH>Bus</TH>
              <TH>Departure</TH>
              <TH>Capacity</TH>
              <TH>Booked</TH>
              <TH className="text-right">Passengers</TH>
            </HeaderRow>
          </THead>
          <TBody>
            {schedules.map((s) => (
              <Row key={s.id}>
                <TD className="font-medium">{s.route.name}</TD>
                <TD className="font-mono text-[12px]">{s.bus_no}</TD>
                <TD className="text-muted">{s.departure_time}</TD>
                <TD className="tabular-nums">{s.capacity}</TD>
                <TD>
                  <StatusPill
                    status={String(s.booked_count)}
                    tone={s.booked_count >= s.capacity ? "warn" : "info"}
                  />
                </TD>
                <TD className="text-right">
                  <Button size="sm" variant="secondary" onClick={() => viewPassengers(s)}>
                    View passengers
                  </Button>
                </TD>
              </Row>
            ))}
          </TBody>
        </Table>
      </DataPanel>

      {selected && (
        <DataPanel
          title={`Passengers — ${selected.route.name} (${selected.bus_no})`}
          loading={bookingsLoading}
          error={bookingsError}
          isEmpty={bookings.length === 0}
          emptyLabel="No bookings for this schedule."
        >
          <Table>
            <THead>
              <HeaderRow>
                <TH>Seat</TH>
                <TH>Student</TH>
                <TH>Status</TH>
              </HeaderRow>
            </THead>
            <TBody>
              {bookings.map((b) => (
                <Row key={b.id}>
                  <TD className="font-medium tabular-nums">{b.seat_no}</TD>
                  <TD className="font-mono text-[12px]">{b.student_id}</TD>
                  <TD>
                    <StatusPill status={b.status} />
                  </TD>
                </Row>
              ))}
            </TBody>
          </Table>
        </DataPanel>
      )}
    </div>
  );
}

export default function DriverDashboard() {
  return (
    <DashboardShell title="My schedules" role="driver">
      <DriverContent />
    </DashboardShell>
  );
}
