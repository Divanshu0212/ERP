"use client";

import { useCallback, useEffect, useState } from "react";

import { DashboardShell } from "@/components/DashboardShell";
import { DataPanel } from "@/components/DataPanel";
import { api, ApiError } from "@/lib/api";
import { listItems, listTotal } from "@/lib/paginate";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { StatCard } from "@/components/ui/StatCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { Field } from "@/components/ui/Field";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Alert";
import { Table, TBody, TD, TH, THead, HeaderRow, Row } from "@/components/ui/Table";

// The admin console manages a single institution (the caller's tenant): headline
// counts, the user roster, and user creation. The institution identity lives in
// the app shell. The gateway scopes every response to the caller's institution.

interface User {
  id: string;
  email: string;
  user_code: string | null;
  role: string;
  is_active: boolean;
  date_joined: string;
}

interface Block {
  id: string;
  name: string;
  gender_type: string;
  warden_id: string;
}

interface HostelRoom {
  id: string;
  block_name: string;
  room_no: string;
  capacity: number;
  occupied_count: number;
}

const ROLES = ["student", "faculty", "warden", "driver", "canteen_owner", "admin", "alumni"] as const;
type Role = (typeof ROLES)[number];

interface StatDef {
  key: string;
  label: string;
  path: string;
}

// Cross-service headline counts: each service exposes a paginated list; we ask
// for one row and read the envelope total.
const CROSS_STATS: StatDef[] = [
  { key: "invoices", label: "Invoices", path: "/api/v1/finance/invoices?limit=1" },
  { key: "allocations", label: "Allocations", path: "/api/v1/hostel/allocations?limit=1" },
  { key: "tickets", label: "Tickets", path: "/api/v1/grievance?limit=1" },
];

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return e instanceof Error ? e.message : "Something went wrong.";
}

function formatDate(value: string): string {
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString();
}

/** Pull a field-level message out of an ApiError's errors payload, if present. */
function fieldErrorMessage(e: unknown): string | null {
  if (!(e instanceof ApiError) || !e.errors || typeof e.errors !== "object") return null;
  const errors = e.errors as Record<string, unknown>;
  for (const value of Object.values(errors)) {
    if (typeof value === "string") return value;
    if (Array.isArray(value) && typeof value[0] === "string") return value[0];
  }
  return null;
}

interface StatState {
  count: number | null;
  error: string | null;
}

function AdminContent() {
  const [statsLoading, setStatsLoading] = useState(true);
  const [userCount, setUserCount] = useState<StatState>({ count: null, error: null });
  const [crossStats, setCrossStats] = useState<Record<string, StatState>>({});

  const [users, setUsers] = useState<User[]>([]);
  const [usersLoading, setUsersLoading] = useState(true);
  const [usersError, setUsersError] = useState<string | null>(null);

  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("student");
  const [password, setPassword] = useState("");
  const [userCode, setUserCode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [formSuccess, setFormSuccess] = useState<string | null>(null);

  const loadCrossStats = useCallback(async () => {
    setStatsLoading(true);
    const results = await Promise.all(
      CROSS_STATS.map(async (s) => {
        try {
          const data = await api.get(s.path);
          return [s.key, { count: listTotal(data), error: null }] as const;
        } catch (e) {
          return [s.key, { count: null, error: errMsg(e) }] as const;
        }
      }),
    );
    setCrossStats(Object.fromEntries(results));
    setStatsLoading(false);
  }, []);

  // Derives the Users count from the roster envelope so table + card agree.
  const loadUsers = useCallback(async () => {
    setUsersLoading(true);
    setUsersError(null);
    try {
      const data = await api.get("/api/v1/auth/users");
      setUsers(listItems<User>(data));
      setUserCount({ count: listTotal(data), error: null });
    } catch (e) {
      setUsersError(errMsg(e));
      setUserCount({ count: null, error: errMsg(e) });
    } finally {
      setUsersLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadCrossStats();
    void loadUsers();
  }, [loadCrossStats, loadUsers]);

  const onSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setSubmitting(true);
      setFormError(null);
      setFormSuccess(null);
      try {
        const created = await api.post<{ email: string }>("/api/v1/auth/users", {
          email,
          role,
          password,
          user_code: userCode,
        });
        setEmail("");
        setRole("student");
        setPassword("");
        setUserCode("");
        setFormSuccess(`Created user ${created?.email ?? email}.`);
        await loadUsers();
      } catch (err) {
        setFormError(fieldErrorMessage(err) ?? errMsg(err));
      } finally {
        setSubmitting(false);
      }
    },
    [email, role, password, userCode, loadUsers],
  );

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Users" loading={usersLoading} error={userCount.error} value={userCount.count} />
        {CROSS_STATS.map((s) => (
          <StatCard
            key={s.key}
            label={s.label}
            loading={statsLoading}
            error={crossStats[s.key]?.error}
            value={crossStats[s.key]?.count ?? null}
          />
        ))}
      </div>

      <CreateInvoice onCreated={loadCrossStats} />

      <FeeStructures />

      <DataPanel
        title="Users"
        loading={usersLoading}
        error={usersError}
        isEmpty={users.length === 0}
        emptyLabel="No users yet. Add one below."
      >
        <Table>
          <THead>
            <HeaderRow>
              <TH>Email</TH>
              <TH>Role</TH>
              <TH>Status</TH>
              <TH>Joined</TH>
            </HeaderRow>
          </THead>
          <TBody>
            {users.map((u) => (
              <Row key={u.id}>
                <TD className="font-medium">{u.email}</TD>
                <TD className="capitalize text-muted">{u.role}</TD>
                <TD>
                  <StatusPill status={u.is_active ? "active" : "inactive"} />
                </TD>
                <TD className="text-muted">{formatDate(u.date_joined)}</TD>
              </Row>
            ))}
          </TBody>
        </Table>
      </DataPanel>

      <Card>
        <CardHeader title="Add user" />
        <CardBody>
          <form onSubmit={onSubmit} className="space-y-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <Field label="Email" htmlFor="new-user-email">
                <Input
                  id="new-user-email"
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </Field>
              <Field label="Role" htmlFor="new-user-role">
                <Select
                  id="new-user-role"
                  value={role}
                  onChange={(e) => setRole(e.target.value as Role)}
                >
                  {ROLES.map((r) => (
                    <option key={r} value={r} className="capitalize">
                      {r}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Password" htmlFor="new-user-password">
                <Input
                  id="new-user-password"
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </Field>
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <Field label="User Code" htmlFor="new-user-code">
                <Input
                  id="new-user-code"
                  required
                  value={userCode}
                  onChange={(e) => setUserCode(e.target.value)}
                  placeholder="e.g. STU001"
                />
              </Field>
            </div>

            {formError && <Alert tone="error">{formError}</Alert>}
            {formSuccess && <Alert tone="success">{formSuccess}</Alert>}

            <Button type="submit" loading={submitting}>
              Add User
            </Button>
          </form>
        </CardBody>
      </Card>

      <HostelSetup />
    </div>
  );
}

function CreateInvoice({ onCreated }: { onCreated: () => void }) {
  const [studentUserCode, setStudentUserCode] = useState("");
  const [amount, setAmount] = useState("");
  const [purpose, setPurpose] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    setOk(null);
    try {
      await api.post("/api/v1/finance/invoices", {
        student_user_code: studentUserCode,
        amount,
        purpose,
      });
      setOk("Invoice created.");
      setStudentUserCode("");
      setAmount("");
      setPurpose("");
      onCreated();
    } catch (err) {
      setError(fieldErrorMessage(err) ?? errMsg(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Create invoice" />
      <CardBody>
        <form onSubmit={submit} className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Field label="Student user code" htmlFor="inv-student">
              <Input
                id="inv-student"
                value={studentUserCode}
                onChange={(e) => setStudentUserCode(e.target.value)}
                required
              />
            </Field>
            <Field label="Amount" htmlFor="inv-amount">
              <Input
                id="inv-amount"
                type="number"
                min={0}
                step="0.01"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                required
              />
            </Field>
            <Field label="Purpose" htmlFor="inv-purpose">
              <Input
                id="inv-purpose"
                value={purpose}
                onChange={(e) => setPurpose(e.target.value)}
                required
              />
            </Field>
          </div>
          {error && <Alert tone="error">{error}</Alert>}
          {ok && <Alert tone="success">{ok}</Alert>}
          <Button type="submit" loading={pending}>
            Create invoice
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}

interface FeeStructure {
  id: string;
  name: string;
  amount: string;
  purpose: string;
}

function FeeStructures() {
  const [feeStructures, setFeeStructures] = useState<FeeStructure[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get("/api/v1/finance/fee-structures");
      setFeeStructures(listItems<FeeStructure>(data));
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-6">
      <CreateFeeStructure onCreated={load} />
      <DataPanel
        title="Fee structures"
        loading={loading}
        error={error}
        isEmpty={feeStructures.length === 0}
        emptyLabel="No fee structures yet. Add one below."
      >
        <Table>
          <THead>
            <HeaderRow>
              <TH>Name</TH>
              <TH>Purpose</TH>
              <TH>Amount</TH>
            </HeaderRow>
          </THead>
          <TBody>
            {feeStructures.map((f) => (
              <Row key={f.id}>
                <TD className="font-medium">{f.name}</TD>
                <TD className="text-muted">{f.purpose}</TD>
                <TD>{f.amount}</TD>
              </Row>
            ))}
          </TBody>
        </Table>
      </DataPanel>
    </div>
  );
}

function CreateFeeStructure({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const [amount, setAmount] = useState("");
  const [purpose, setPurpose] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    setOk(null);
    try {
      await api.post("/api/v1/finance/fee-structures", { name, amount, purpose });
      setOk("Fee structure created.");
      setName("");
      setAmount("");
      setPurpose("");
      onCreated();
    } catch (err) {
      setError(fieldErrorMessage(err) ?? errMsg(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Create fee structure" />
      <CardBody>
        <form onSubmit={submit} className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Field label="Name" htmlFor="fee-name">
              <Input id="fee-name" value={name} onChange={(e) => setName(e.target.value)} required />
            </Field>
            <Field label="Purpose" htmlFor="fee-purpose">
              <Input
                id="fee-purpose"
                value={purpose}
                onChange={(e) => setPurpose(e.target.value)}
                placeholder="hostel"
                required
              />
            </Field>
            <Field label="Amount" htmlFor="fee-amount">
              <Input
                id="fee-amount"
                type="number"
                min={0}
                step="0.01"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                required
              />
            </Field>
          </div>
          {error && <Alert tone="error">{error}</Alert>}
          {ok && <Alert tone="success">{ok}</Alert>}
          <Button type="submit" loading={pending}>
            Create fee structure
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}

function HostelSetup() {
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [blocksLoading, setBlocksLoading] = useState(true);
  const [blocksError, setBlocksError] = useState<string | null>(null);

  const [rooms, setRooms] = useState<HostelRoom[]>([]);
  const [roomsLoading, setRoomsLoading] = useState(true);
  const [roomsError, setRoomsError] = useState<string | null>(null);

  const loadBlocks = useCallback(async () => {
    setBlocksLoading(true);
    setBlocksError(null);
    try {
      const data = await api.get("/api/v1/hostel/blocks");
      setBlocks(listItems<Block>(data));
    } catch (e) {
      setBlocksError(errMsg(e));
    } finally {
      setBlocksLoading(false);
    }
  }, []);

  const loadRooms = useCallback(async () => {
    setRoomsLoading(true);
    setRoomsError(null);
    try {
      const data = await api.get("/api/v1/hostel/rooms");
      setRooms(listItems<HostelRoom>(data));
    } catch (e) {
      setRoomsError(errMsg(e));
    } finally {
      setRoomsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadBlocks();
    void loadRooms();
  }, [loadBlocks, loadRooms]);

  return (
    <div className="space-y-6">
      <CreateBlock onCreated={loadBlocks} />
      <DataPanel
        title="Blocks"
        loading={blocksLoading}
        error={blocksError}
        isEmpty={blocks.length === 0}
        emptyLabel="No blocks yet. Add one below."
      >
        <Table>
          <THead>
            <HeaderRow>
              <TH>Name</TH>
              <TH>Gender</TH>
              <TH>Warden</TH>
            </HeaderRow>
          </THead>
          <TBody>
            {blocks.map((b) => (
              <Row key={b.id}>
                <TD className="font-medium">{b.name}</TD>
                <TD className="text-muted">{b.gender_type}</TD>
                <TD className="font-mono text-[12px]">{b.warden_id}</TD>
              </Row>
            ))}
          </TBody>
        </Table>
      </DataPanel>

      <CreateRoom blocks={blocks} onCreated={loadRooms} />
      <DataPanel
        title="Rooms"
        loading={roomsLoading}
        error={roomsError}
        isEmpty={rooms.length === 0}
        emptyLabel="No rooms yet. Add one below."
      >
        <Table>
          <THead>
            <HeaderRow>
              <TH>Block</TH>
              <TH>Room no.</TH>
              <TH>Occupancy</TH>
            </HeaderRow>
          </THead>
          <TBody>
            {rooms.map((r) => (
              <Row key={r.id}>
                <TD className="font-medium">{r.block_name}</TD>
                <TD>{r.room_no}</TD>
                <TD className="text-muted">
                  {r.occupied_count}/{r.capacity}
                </TD>
              </Row>
            ))}
          </TBody>
        </Table>
      </DataPanel>
    </div>
  );
}

function CreateBlock({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const [genderType, setGenderType] = useState<"M" | "F">("M");
  const [wardenUserCode, setWardenUserCode] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    setOk(null);
    try {
      await api.post("/api/v1/hostel/blocks", {
        name,
        gender_type: genderType,
        warden_user_code: wardenUserCode,
      });
      setOk("Block created.");
      setName("");
      setWardenUserCode("");
      onCreated();
    } catch (err) {
      setError(fieldErrorMessage(err) ?? errMsg(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Create block" />
      <CardBody>
        <form onSubmit={submit} className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Field label="Name" htmlFor="block-name">
              <Input id="block-name" value={name} onChange={(e) => setName(e.target.value)} required />
            </Field>
            <Field label="Gender type" htmlFor="block-gender">
              <Select
                id="block-gender"
                value={genderType}
                onChange={(e) => setGenderType(e.target.value as "M" | "F")}
              >
                <option value="M">Male</option>
                <option value="F">Female</option>
              </Select>
            </Field>
            <Field label="Warden user code" htmlFor="block-warden">
              <Input
                id="block-warden"
                value={wardenUserCode}
                onChange={(e) => setWardenUserCode(e.target.value)}
                required
              />
            </Field>
          </div>
          {error && <Alert tone="error">{error}</Alert>}
          {ok && <Alert tone="success">{ok}</Alert>}
          <Button type="submit" loading={pending}>
            Create block
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}

function CreateRoom({ blocks, onCreated }: { blocks: Block[]; onCreated: () => void }) {
  const [blockId, setBlockId] = useState("");
  const [roomNo, setRoomNo] = useState("");
  const [capacity, setCapacity] = useState("2");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    setOk(null);
    try {
      await api.post("/api/v1/hostel/rooms", {
        block_id: blockId,
        room_no: roomNo,
        capacity: Number(capacity),
      });
      setOk("Room created.");
      setRoomNo("");
      onCreated();
    } catch (err) {
      setError(fieldErrorMessage(err) ?? errMsg(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Create room" />
      <CardBody>
        <form onSubmit={submit} className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Field label="Block" htmlFor="room-block">
              <Select id="room-block" value={blockId} onChange={(e) => setBlockId(e.target.value)} required>
                <option value="" disabled>
                  Select a block
                </option>
                {blocks.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Room number" htmlFor="room-no">
              <Input id="room-no" value={roomNo} onChange={(e) => setRoomNo(e.target.value)} required />
            </Field>
            <Field label="Capacity" htmlFor="room-capacity">
              <Input
                id="room-capacity"
                type="number"
                min={1}
                value={capacity}
                onChange={(e) => setCapacity(e.target.value)}
                required
              />
            </Field>
          </div>
          {error && <Alert tone="error">{error}</Alert>}
          {ok && <Alert tone="success">{ok}</Alert>}
          <Button type="submit" loading={pending}>
            Create room
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}

export default function AdminDashboard() {
  return (
    <DashboardShell title="Admin" role="admin">
      <AdminContent />
    </DashboardShell>
  );
}
