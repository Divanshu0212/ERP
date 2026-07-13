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
  student_user_code: string;
  room_id: string;
  room_name: string;
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

interface FeeStructure {
  id: string;
  name: string;
  amount: string;
  purpose: string;
}

interface PendingRequest {
  id: string;
  student_id: string;
  room_id: string;
  room_name: string;
  status: string;
  requested_on: string;
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

  const [releaseError, setReleaseError] = useState<string | null>(null);

  const loadAllocations = useCallback(async () => {
    setAllocLoading(true);
    setAllocError(null);
    try {
      const [pendingData, confirmedData] = await Promise.all([
        api.get("/api/v1/hostel/allocations?status=pending"),
        api.get("/api/v1/hostel/allocations?status=confirmed"),
      ]);
      setAllocations([
        ...listItems<Allocation>(pendingData),
        ...listItems<Allocation>(confirmedData),
      ]);
    } catch (e) {
      setAllocError(errMsg(e));
    } finally {
      setAllocLoading(false);
    }
  }, []);

  async function releaseAllocation(id: string) {
    setReleaseError(null);
    try {
      await api.post(`/api/v1/hostel/allocations/${id}/release`, {});
      await loadAllocations();
    } catch (err) {
      setReleaseError(errMsg(err));
    }
  }

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
        roomsLoading={roomsLoading}
        onCreated={() => {
          void loadAllocations();
          void loadRooms();
        }}
      />

      <BulkAllocationImport
        onImported={() => {
          void loadAllocations();
          void loadRooms();
        }}
      />

      <ImportLogs />

      <RoomRequestQueue />

      <DataPanel
        title="Hostel allocations"
        loading={allocLoading}
        error={allocError}
        isEmpty={allocations.length === 0}
        emptyLabel="No active allocations."
      >
        {releaseError && <Alert tone="error">{releaseError}</Alert>}
        <Table>
          <THead>
            <HeaderRow>
              <TH>Student</TH>
              <TH>Room</TH>
              <TH>Status</TH>
              <TH />
            </HeaderRow>
          </THead>
          <TBody>
            {allocations.map((a) => (
              <Row key={a.id}>
                <TD className="font-mono text-[12px]">{a.student_user_code}</TD>
                <TD className="font-medium">{a.room_name}</TD>
                <TD>
                  <StatusPill status={a.status} />
                </TD>
                <TD>
                  <Button type="button" onClick={() => releaseAllocation(a.id)}>
                    Release
                  </Button>
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

function CreateAllocation({
  rooms,
  roomsLoading,
  onCreated,
}: {
  rooms: Room[];
  roomsLoading: boolean;
  onCreated: () => void;
}) {
  const [roomId, setRoomId] = useState("");
  const [studentUserCode, setStudentUserCode] = useState("");
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
        student_user_code: studentUserCode,
      });
      setOk("Allocation created.");
      setRoomId("");
      setStudentUserCode("");
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
                disabled={roomsLoading}
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
            <Field label="Student user code" htmlFor="alloc-student">
              <Input
                id="alloc-student"
                value={studentUserCode}
                onChange={(e) => setStudentUserCode(e.target.value)}
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

interface BulkImportSummary {
  batch_id: string;
  total_rows: number;
  success_count: number;
  fail_count: number;
  skipped_count: number;
}

function BulkAllocationImport({ onImported }: { onImported: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<BulkImportSummary | null>(null);
  const [templateError, setTemplateError] = useState<string | null>(null);
  const [templatePending, setTemplatePending] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setPending(true);
    setError(null);
    setSummary(null);
    try {
      const result = await api.upload<BulkImportSummary>("/api/v1/hostel/allocate/bulk", file);
      setSummary(result);
      setFile(null);
      onImported();
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setPending(false);
    }
  }

  async function downloadTemplate() {
    setTemplatePending(true);
    setTemplateError(null);
    try {
      await api.download("/api/v1/hostel/rooms/available-template", "allocation-template.csv");
    } catch (err) {
      setTemplateError(errMsg(err));
    } finally {
      setTemplatePending(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Bulk allocate from CSV/XLSX" />
      <CardBody>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              loading={templatePending}
              onClick={downloadTemplate}
            >
              Download available-rooms template
            </Button>
            {templateError && <Alert tone="error">{templateError}</Alert>}
          </div>
          <Field label="File" htmlFor="bulk-file">
            <input
              id="bulk-file"
              type="file"
              accept=".csv,.xlsx"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="block w-full text-sm text-ink"
            />
          </Field>
          {error && <Alert tone="error">{error}</Alert>}
          {summary && (
            <Alert tone={summary.fail_count > 0 ? "info" : "success"}>
              {summary.success_count} succeeded, {summary.fail_count} failed,{" "}
              {summary.skipped_count} skipped out of {summary.total_rows}. See Import
              Logs below for details.
            </Alert>
          )}
          <Button type="submit" loading={pending} disabled={!file}>
            Upload
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}

interface ImportBatch {
  id: string;
  filename: string;
  total_rows: number;
  success_count: number;
  fail_count: number;
  skipped_count: number;
  created_at: string;
}

interface ImportRow {
  row_number: number;
  room_id_raw: string;
  student_user_code_raw: string;
  status: string;
  error_message: string;
  allocation_id: string | null;
}

function ImportLogs() {
  const [batches, setBatches] = useState<ImportBatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [rows, setRows] = useState<ImportRow[]>([]);
  const [rowsLoading, setRowsLoading] = useState(false);

  const loadBatches = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get("/api/v1/hostel/allocations/import-logs");
      setBatches(listItems<ImportBatch>(data));
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadBatches();
  }, [loadBatches]);

  async function viewBatch(id: string) {
    setSelectedId(id);
    setRowsLoading(true);
    try {
      const data = await api.get<{ rows: ImportRow[] }>(`/api/v1/hostel/allocations/import-logs/${id}`);
      setRows(data.rows ?? []);
    } finally {
      setRowsLoading(false);
    }
  }

  return (
    <DataPanel
      title="Import logs"
      loading={loading}
      error={error}
      isEmpty={batches.length === 0}
      emptyLabel="No bulk imports yet."
    >
      <Table>
        <THead>
          <HeaderRow>
            <TH>File</TH>
            <TH>Uploaded</TH>
            <TH>Success</TH>
            <TH>Failed</TH>
            <TH>Skipped</TH>
            <TH />
          </HeaderRow>
        </THead>
        <TBody>
          {batches.map((b) => (
            <Row key={b.id}>
              <TD className="font-medium">{b.filename}</TD>
              <TD className="text-muted">{new Date(b.created_at).toLocaleString()}</TD>
              <TD>{b.success_count}</TD>
              <TD>{b.fail_count}</TD>
              <TD>{b.skipped_count}</TD>
              <TD>
                <Button variant="ghost" size="sm" onClick={() => viewBatch(b.id)}>
                  View
                </Button>
              </TD>
            </Row>
          ))}
        </TBody>
      </Table>

      {selectedId &&
        (rowsLoading ? (
          <p className="mt-4 text-[13px] text-muted">Loading…</p>
        ) : (
          <Table>
            <THead>
              <HeaderRow>
                <TH>Row</TH>
                <TH>Room ID</TH>
                <TH>Student user code</TH>
                <TH>Status</TH>
                <TH>Error</TH>
              </HeaderRow>
            </THead>
            <TBody>
              {rows.map((r) => (
                <Row key={r.row_number}>
                  <TD>{r.row_number}</TD>
                  <TD className="font-mono text-[12px]">{r.room_id_raw}</TD>
                  <TD>{r.student_user_code_raw}</TD>
                  <TD>
                    <StatusPill status={r.status} />
                  </TD>
                  <TD className="text-muted">{r.error_message}</TD>
                </Row>
              ))}
            </TBody>
          </Table>
        ))}
    </DataPanel>
  );
}

function RoomRequestQueue() {
  const [requests, setRequests] = useState<PendingRequest[]>([]);
  const [feeStructures, setFeeStructures] = useState<FeeStructure[]>([]);
  const [selectedFee, setSelectedFee] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [requestsData, feesData] = await Promise.all([
        api.get("/api/v1/hostel/room-requests?status=pending"),
        api.get("/api/v1/finance/fee-structures"),
      ]);
      setRequests(listItems<PendingRequest>(requestsData));
      setFeeStructures(listItems<FeeStructure>(feesData));
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function approve(id: string) {
    const feeStructureId = selectedFee[id];
    if (!feeStructureId) {
      setActionError("Pick a fee structure before approving.");
      return;
    }
    setActionError(null);
    try {
      await api.post(`/api/v1/hostel/room-requests/${id}/approve`, {
        fee_structure_id: feeStructureId,
      });
      await load();
    } catch (err) {
      setActionError(errMsg(err));
    }
  }

  async function reject(id: string) {
    setActionError(null);
    try {
      await api.post(`/api/v1/hostel/room-requests/${id}/reject`, {});
      await load();
    } catch (err) {
      setActionError(errMsg(err));
    }
  }

  return (
    <DataPanel
      title="Pending room requests"
      loading={loading}
      error={error}
      isEmpty={requests.length === 0}
      emptyLabel="No pending room requests."
    >
      {actionError && <Alert tone="error">{actionError}</Alert>}
      <Table>
        <THead>
          <HeaderRow>
            <TH>Room</TH>
            <TH>Requested</TH>
            <TH>Fee</TH>
            <TH />
          </HeaderRow>
        </THead>
        <TBody>
          {requests.map((r) => (
            <Row key={r.id}>
              <TD className="font-medium">{r.room_name}</TD>
              <TD className="text-muted">{new Date(r.requested_on).toLocaleString()}</TD>
              <TD>
                <Select
                  value={selectedFee[r.id] ?? ""}
                  onChange={(e) =>
                    setSelectedFee((prev) => ({ ...prev, [r.id]: e.target.value }))
                  }
                >
                  <option value="">Select fee…</option>
                  {feeStructures.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.name} ({f.amount})
                    </option>
                  ))}
                </Select>
              </TD>
              <TD className="space-x-2">
                <Button size="sm" onClick={() => void approve(r.id)}>
                  Approve
                </Button>
                <Button size="sm" variant="ghost" onClick={() => void reject(r.id)}>
                  Reject
                </Button>
              </TD>
            </Row>
          ))}
        </TBody>
      </Table>
    </DataPanel>
  );
}

export default function WardenDashboard() {
  return (
    <DashboardShell title="Overview" role="warden">
      <WardenContent />
    </DashboardShell>
  );
}
