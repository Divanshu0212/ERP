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

interface Allocation {
  id: string;
  student_id: string;
  room: string;
  status: string;
}

interface Grievance {
  id: string;
  raised_by: string;
  status: string;
  assigned_to: string;
}

interface Room {
  id: string;
  block_name: string;
  room_no: string;
  capacity: number;
  occupied_count: number;
}

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return e instanceof Error ? e.message : "Something went wrong.";
}

function WardenContent() {
  const [allocations, setAllocations] = useState<Allocation[]>([]);
  const [allocLoading, setAllocLoading] = useState(true);
  const [allocError, setAllocError] = useState<string | null>(null);

  const [grievances, setGrievances] = useState<Grievance[]>([]);
  const [grievLoading, setGrievLoading] = useState(true);
  const [grievError, setGrievError] = useState<string | null>(null);

  const loadAllocations = useCallback(async () => {
    setAllocLoading(true);
    setAllocError(null);
    try {
      const data = await api.get("/api/v1/hostel/allocations?status=pending");
      setAllocations(listItems<Allocation>(data));
    } catch (e) {
      setAllocError(errMsg(e));
    } finally {
      setAllocLoading(false);
    }
  }, []);

  const loadGrievances = useCallback(async () => {
    setGrievLoading(true);
    setGrievError(null);
    try {
      const data = await api.get("/api/v1/grievance?status=escalated");
      setGrievances(listItems<Grievance>(data));
    } catch (e) {
      setGrievError(errMsg(e));
    } finally {
      setGrievLoading(false);
    }
  }, []);

  const [rooms, setRooms] = useState<Room[]>([]);
  const [roomsLoading, setRoomsLoading] = useState(true);

  const loadRooms = useCallback(async () => {
    setRoomsLoading(true);
    try {
      const data = await api.get("/api/v1/hostel/rooms/available");
      setRooms(listItems<Room>(data));
    } finally {
      setRoomsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAllocations();
    void loadGrievances();
    void loadRooms();
  }, [loadAllocations, loadGrievances, loadRooms]);

  return (
    <div className="space-y-6">
      <CreateAllocation
        rooms={rooms}
        onCreated={() => {
          void loadAllocations();
          void loadRooms();
        }}
      />

      <DataPanel
        title="Pending hostel allocations"
        loading={allocLoading}
        error={allocError}
        isEmpty={allocations.length === 0}
        emptyLabel="No pending allocations."
      >
        <Table>
          <THead>
            <HeaderRow>
              <TH>Student</TH>
              <TH>Room</TH>
              <TH>Status</TH>
            </HeaderRow>
          </THead>
          <TBody>
            {allocations.map((a) => (
              <Row key={a.id}>
                <TD className="font-mono text-[12px]">{a.student_id}</TD>
                <TD className="font-medium">{a.room}</TD>
                <TD>
                  <StatusPill status={a.status} />
                </TD>
              </Row>
            ))}
          </TBody>
        </Table>
      </DataPanel>

      <DataPanel
        title="Escalated grievances"
        loading={grievLoading}
        error={grievError}
        isEmpty={grievances.length === 0}
        emptyLabel="No escalated grievances."
      >
        <Table>
          <THead>
            <HeaderRow>
              <TH>Ticket</TH>
              <TH>Raised by</TH>
              <TH>Status</TH>
              <TH>Assigned to</TH>
            </HeaderRow>
          </THead>
          <TBody>
            {grievances.map((g) => (
              <Row key={g.id}>
                <TD className="font-mono text-[12px]">{g.id}</TD>
                <TD>{g.raised_by}</TD>
                <TD>
                  <StatusPill status={g.status} />
                </TD>
                <TD className="text-muted">{g.assigned_to}</TD>
              </Row>
            ))}
          </TBody>
        </Table>
      </DataPanel>
    </div>
  );
}

function CreateAllocation({ rooms, onCreated }: { rooms: Room[]; onCreated: () => void }) {
  const [roomId, setRoomId] = useState("");
  const [studentEmail, setStudentEmail] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    setOk(null);
    try {
      await api.post("/api/v1/hostel/allocate", {
        room_id: roomId,
        student_email: studentEmail,
      });
      setOk("Allocation created.");
      setRoomId("");
      setStudentEmail("");
      onCreated();
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Create allocation" />
      <CardBody>
        <form onSubmit={submit} className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Room" htmlFor="alloc-room">
              <Select
                id="alloc-room"
                value={roomId}
                onChange={(e) => setRoomId(e.target.value)}
                required
              >
                <option value="" disabled>
                  Select a room
                </option>
                {rooms.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.block_name}/{r.room_no} ({r.occupied_count}/{r.capacity})
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Student email" htmlFor="alloc-student">
              <Input
                id="alloc-student"
                type="email"
                value={studentEmail}
                onChange={(e) => setStudentEmail(e.target.value)}
                required
              />
            </Field>
          </div>
          {error && <Alert tone="error">{error}</Alert>}
          {ok && <Alert tone="success">{ok}</Alert>}
          <Button type="submit" loading={pending}>
            Create allocation
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}

export default function WardenDashboard() {
  return (
    <DashboardShell title="Overview" role="warden">
      <WardenContent />
    </DashboardShell>
  );
}
