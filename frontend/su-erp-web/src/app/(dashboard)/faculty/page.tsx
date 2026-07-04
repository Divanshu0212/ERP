"use client";

import { useCallback, useEffect, useState } from "react";

import { DashboardShell } from "@/components/DashboardShell";
import { DataPanel } from "@/components/DataPanel";
import { api, ApiError } from "@/lib/api";
import { listItems } from "@/lib/paginate";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Alert } from "@/components/ui/Alert";
import { StatusPill } from "@/components/ui/StatusPill";
import { Table, TBody, TD, TH, THead, HeaderRow, Row } from "@/components/ui/Table";

interface AttendanceRecord {
  id: string;
  student_id: string;
  course_id: string;
  date: string;
  status: string;
  created_at: string;
}

interface ExamSchedule {
  id: string;
  course_id: string;
  exam_date: string;
  room_no: string;
  duration_minutes: number;
  created_at: string;
}

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

function AttendanceSection() {
  const [records, setRecords] = useState<AttendanceRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [studentId, setStudentId] = useState("");
  const [courseId, setCourseId] = useState("");
  const [date, setDate] = useState("");
  const [status, setStatus] = useState("present");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await api.get("/api/v1/attendance/records");
      setRecords(listItems<AttendanceRecord>(data));
    } catch (e) {
      setLoadError(errMsg(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    setOk(null);
    try {
      await api.post("/api/v1/attendance/records", {
        student_id: studentId,
        course_id: courseId,
        date,
        status,
      });
      setOk("Attendance recorded.");
      setStudentId("");
      setCourseId("");
      setDate("");
      setStatus("present");
      await load();
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title="Mark attendance" />
        <CardBody>
          <form onSubmit={submit} className="space-y-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
              <Field label="Student ID" htmlFor="att-student">
                <Input
                  id="att-student"
                  value={studentId}
                  onChange={(e) => setStudentId(e.target.value)}
                  required
                />
              </Field>
              <Field label="Course ID" htmlFor="att-course">
                <Input
                  id="att-course"
                  value={courseId}
                  onChange={(e) => setCourseId(e.target.value)}
                  required
                />
              </Field>
              <Field label="Date" htmlFor="att-date">
                <Input
                  id="att-date"
                  type="date"
                  value={date}
                  onChange={(e) => setDate(e.target.value)}
                  required
                />
              </Field>
              <Field label="Status" htmlFor="att-status">
                <Select
                  id="att-status"
                  value={status}
                  onChange={(e) => setStatus(e.target.value)}
                >
                  <option value="present">Present</option>
                  <option value="absent">Absent</option>
                </Select>
              </Field>
            </div>
            {error && <Alert tone="error">{error}</Alert>}
            {ok && <Alert tone="success">{ok}</Alert>}
            <Button type="submit" loading={pending}>
              Mark attendance
            </Button>
          </form>
        </CardBody>
      </Card>

      <DataPanel
        title="Recent attendance"
        loading={loading}
        error={loadError}
        isEmpty={records.length === 0}
        emptyLabel="No attendance records yet."
      >
        <Table>
          <THead>
            <HeaderRow>
              <TH>Student</TH>
              <TH>Course</TH>
              <TH>Date</TH>
              <TH>Status</TH>
            </HeaderRow>
          </THead>
          <TBody>
            {records.map((r) => (
              <Row key={r.id}>
                <TD className="font-mono text-[12px]">{r.student_id}</TD>
                <TD className="font-mono text-[12px]">{r.course_id}</TD>
                <TD className="text-muted">{r.date}</TD>
                <TD>
                  <StatusPill status={r.status} />
                </TD>
              </Row>
            ))}
          </TBody>
        </Table>
      </DataPanel>
    </div>
  );
}

function ExamSection() {
  const [schedules, setSchedules] = useState<ExamSchedule[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [courseId, setCourseId] = useState("");
  const [examDate, setExamDate] = useState("");
  const [roomNo, setRoomNo] = useState("");
  const [duration, setDuration] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await api.get("/api/v1/exams/schedules");
      setSchedules(listItems<ExamSchedule>(data));
    } catch (e) {
      setLoadError(errMsg(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    setOk(null);
    try {
      await api.post("/api/v1/exams/schedules", {
        course_id: courseId,
        exam_date: examDate,
        room_no: roomNo,
        duration_minutes: Number(duration),
      });
      setOk("Exam schedule created.");
      setCourseId("");
      setExamDate("");
      setRoomNo("");
      setDuration("");
      await load();
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title="Create exam schedule" />
        <CardBody>
          <form onSubmit={submit} className="space-y-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
              <Field label="Exam course ID" htmlFor="exam-course">
                <Input
                  id="exam-course"
                  value={courseId}
                  onChange={(e) => setCourseId(e.target.value)}
                  required
                />
              </Field>
              <Field label="Exam date" htmlFor="exam-date">
                <Input
                  id="exam-date"
                  type="date"
                  value={examDate}
                  onChange={(e) => setExamDate(e.target.value)}
                  required
                />
              </Field>
              <Field label="Room no" htmlFor="exam-room">
                <Input
                  id="exam-room"
                  value={roomNo}
                  onChange={(e) => setRoomNo(e.target.value)}
                  required
                />
              </Field>
              <Field label="Duration (min)" htmlFor="exam-duration">
                <Input
                  id="exam-duration"
                  type="number"
                  min={1}
                  value={duration}
                  onChange={(e) => setDuration(e.target.value)}
                  required
                />
              </Field>
            </div>
            {error && <Alert tone="error">{error}</Alert>}
            {ok && <Alert tone="success">{ok}</Alert>}
            <Button type="submit" loading={pending}>
              Create schedule
            </Button>
          </form>
        </CardBody>
      </Card>

      <DataPanel
        title="Upcoming exams"
        loading={loading}
        error={loadError}
        isEmpty={schedules.length === 0}
        emptyLabel="No exam schedules yet."
      >
        <Table>
          <THead>
            <HeaderRow>
              <TH>Course</TH>
              <TH>Date</TH>
              <TH>Room</TH>
              <TH>Duration</TH>
            </HeaderRow>
          </THead>
          <TBody>
            {schedules.map((s) => (
              <Row key={s.id}>
                <TD className="font-mono text-[12px]">{s.course_id}</TD>
                <TD className="text-muted">{s.exam_date}</TD>
                <TD className="font-medium">{s.room_no}</TD>
                <TD className="tabular-nums">{s.duration_minutes} min</TD>
              </Row>
            ))}
          </TBody>
        </Table>
      </DataPanel>
    </div>
  );
}

export default function FacultyDashboard() {
  return (
    <DashboardShell title="Faculty" role="faculty">
      <div className="space-y-6">
        <AttendanceSection />
        <ExamSection />
      </div>
    </DashboardShell>
  );
}
