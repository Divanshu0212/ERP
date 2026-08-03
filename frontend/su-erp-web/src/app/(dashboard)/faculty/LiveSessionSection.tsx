"use client";

import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { listItems } from "@/lib/paginate";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { DataPanel } from "@/components/DataPanel";
import { Field } from "@/components/ui/Field";
import { Input } from "@/components/ui/Input";
import { Table, TBody, TD, TH, THead, HeaderRow, Row } from "@/components/ui/Table";

/**
 * The faculty half of geofenced attendance: open a session pinned to the
 * room, project the rotating code, watch students land, close it.
 *
 * Students mark from the mobile app; this is the only surface that can start
 * that flow, so it deliberately shows the code at projector size rather than
 * as another field in a form.
 */

interface AttendanceSession {
  id: string;
  course_code: string;
  faculty_id: string;
  lat: string;
  lng: string;
  radius_m: number;
  opened_at: string;
  closed_at: string | null;
}

interface AttendanceMark {
  id: string;
  session: string;
  student_user_code: string;
  distance_m: number;
  mock_location: boolean;
  marked_at: string;
}

/** Matches attendance.rolling_code.CODE_PERIOD_SECONDS on the server. */
const CODE_POLL_MS = 5_000;
/** The roster is a comfort read, not a control — it can lag a few seconds. */
const ROSTER_POLL_MS = 10_000;

function errMsg(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.errors && typeof e.errors === "object") {
      for (const v of Object.values(e.errors as Record<string, unknown>)) {
        if (Array.isArray(v) && v.length) return String(v[0]);
        if (typeof v === "string") return v;
      }
    }
    return e.message;
  }
  return e instanceof Error ? e.message : "Something went wrong.";
}

function markedAtLabel(iso: string): string {
  const at = new Date(iso);
  return Number.isNaN(at.getTime())
    ? iso
    : at.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

export function LiveSessionSection() {
  const [session, setSession] = useState<AttendanceSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [code, setCode] = useState<string | null>(null);
  const [marks, setMarks] = useState<AttendanceMark[]>([]);

  const [courseCode, setCourseCode] = useState("");
  const [lat, setLat] = useState("");
  const [lng, setLng] = useState("");
  const [radius, setRadius] = useState("50");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  const loadSessions = useCallback(async () => {
    setLoadError(null);
    try {
      const data = await api.get("/api/v1/attendance/sessions");
      const running =
        listItems<AttendanceSession>(data).find((s) => s.closed_at === null) ?? null;
      setSession(running);
      if (running === null) {
        setCode(null);
        setMarks([]);
      }
    } catch (e) {
      setLoadError(errMsg(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

  // Only polls while a session is actually running: an idle console has no
  // business hitting the gateway every five seconds all afternoon.
  useEffect(() => {
    if (session === null) return;

    let cancelled = false;
    const pullCode = async () => {
      try {
        const data = await api.get<{ code: string }>(
          `/api/v1/attendance/sessions/${session.id}/code`,
        );
        if (!cancelled) setCode(data.code);
      } catch {
        // A dropped poll is not worth a banner — the next one is 5s away.
      }
    };

    void pullCode();
    const timer = setInterval(() => void pullCode(), CODE_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [session]);

  useEffect(() => {
    if (session === null) return;

    let cancelled = false;
    const pullMarks = async () => {
      try {
        const data = await api.get<AttendanceMark[]>(
          `/api/v1/attendance/sessions/${session.id}/marks`,
        );
        if (!cancelled) setMarks(Array.isArray(data) ? data : []);
      } catch {
        // Same: the roster refreshes itself shortly.
      }
    };

    void pullMarks();
    const timer = setInterval(() => void pullMarks(), ROSTER_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [session]);

  async function open(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    setOk(null);
    try {
      await api.post("/api/v1/attendance/sessions", {
        course_code: courseCode,
        lat,
        lng,
        radius_m: Number(radius),
      });
      setOk("Session opened. Project the code below.");
      setCourseCode("");
      await loadSessions();
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setPending(false);
    }
  }

  async function close() {
    if (session === null) return;
    setPending(true);
    setError(null);
    setOk(null);
    try {
      await api.post(`/api/v1/attendance/sessions/${session.id}/close`, {});
      setOk("Session closed.");
      await loadSessions();
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setPending(false);
    }
  }

  /** Fills the geofence from the browser, so nobody types coordinates by hand. */
  function useMyLocation() {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      setError("This browser cannot report a location. Enter the coordinates by hand.");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setLat(position.coords.latitude.toFixed(6));
        setLng(position.coords.longitude.toFixed(6));
      },
      () => setError("Could not read this device's location."),
    );
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title="Live attendance session" />
        <CardBody>
          {loading ? (
            <p role="status" className="text-sm text-muted">
              Loading…
            </p>
          ) : loadError ? (
            <Alert tone="error">{loadError}</Alert>
          ) : session ? (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <p className="text-[13px] font-medium text-muted">
                    {session.course_code} · {session.radius_m} m radius
                  </p>
                  {/* Projector-sized: students read this from the back row. */}
                  <p className="mt-1 text-5xl font-[650] tabular-nums tracking-[0.2em] text-ink">
                    {code ?? "······"}
                  </p>
                  <p className="mt-1 text-[13px] text-muted">
                    Rotates every 15 seconds. A photographed code expires in transit.
                  </p>
                </div>
                <Button type="button" variant="danger" loading={pending} onClick={() => void close()}>
                  Close session
                </Button>
              </div>
              {error && <Alert tone="error">{error}</Alert>}
              {ok && <Alert tone="success">{ok}</Alert>}
            </div>
          ) : (
            <form onSubmit={open} className="space-y-4">
              <p className="text-sm text-muted">No class is running right now.</p>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
                <Field label="Course code" htmlFor="sess-course">
                  <Input
                    id="sess-course"
                    value={courseCode}
                    onChange={(e) => setCourseCode(e.target.value)}
                    required
                  />
                </Field>
                <Field label="Latitude" htmlFor="sess-lat">
                  <Input
                    id="sess-lat"
                    value={lat}
                    onChange={(e) => setLat(e.target.value)}
                    required
                  />
                </Field>
                <Field label="Longitude" htmlFor="sess-lng">
                  <Input
                    id="sess-lng"
                    value={lng}
                    onChange={(e) => setLng(e.target.value)}
                    required
                  />
                </Field>
                <Field label="Radius (m)" htmlFor="sess-radius">
                  <Input
                    id="sess-radius"
                    type="number"
                    min={10}
                    max={500}
                    value={radius}
                    onChange={(e) => setRadius(e.target.value)}
                    required
                  />
                </Field>
              </div>
              {error && <Alert tone="error">{error}</Alert>}
              {ok && <Alert tone="success">{ok}</Alert>}
              <div className="flex flex-wrap gap-3">
                <Button type="submit" loading={pending}>
                  Open session
                </Button>
                <Button type="button" variant="secondary" onClick={useMyLocation}>
                  Use this room&rsquo;s location
                </Button>
              </div>
            </form>
          )}
        </CardBody>
      </Card>

      {session && (
        <DataPanel
          title={`In the room (${marks.length})`}
          loading={false}
          error={null}
          isEmpty={marks.length === 0}
          emptyLabel="Nobody has marked yet."
        >
          <Table>
            <THead>
              <HeaderRow>
                <TH>Student</TH>
                <TH>Marked</TH>
                <TH>Distance</TH>
              </HeaderRow>
            </THead>
            <TBody>
              {marks.map((m) => (
                <Row key={m.id}>
                  <TD className="font-mono text-[12px]">{m.student_user_code}</TD>
                  <TD className="text-muted">{markedAtLabel(m.marked_at)}</TD>
                  <TD className="tabular-nums">{Math.round(m.distance_m)} m</TD>
                </Row>
              ))}
            </TBody>
          </Table>
        </DataPanel>
      )}
    </div>
  );
}
