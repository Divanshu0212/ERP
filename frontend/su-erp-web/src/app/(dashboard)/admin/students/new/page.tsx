"use client";

import { useCallback, useState } from "react";

import { DashboardShell } from "@/components/DashboardShell";
import { api, ApiError } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Field } from "@/components/ui/Field";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Alert";
import { StatusPill } from "@/components/ui/StatusPill";
import { Table, TBody, TD, TH, THead, HeaderRow, Row } from "@/components/ui/Table";

// Both the single-add form and the CSV bulk uploader post to the same
// bulk-create endpoint (Task 2) — there is no separate single-create
// endpoint. The single form just sends a one-row array.
const CSV_HEADER = "email,user_code,password,department,batch,semester";

interface StudentRow {
  email: string;
  user_code: string;
  password: string;
  department: string;
  batch: string;
  semester: number;
}

interface BulkCreateResult {
  created: { row: number; email: string; user_code: string }[];
  failed: { row: number; email: string; error: string }[];
}

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return e instanceof Error ? e.message : "Something went wrong.";
}

/** Minimal CSV parser for the fixed, known-safe student-upload column set —
 * no quoted-field support, since the columns are all plain tokens
 * (email/code/password/free-text department/batch, integer semester). */
function parseStudentCsv(text: string): StudentRow[] {
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter((l) => l.length > 0);
  if (lines.length === 0) throw new Error("CSV file is empty.");

  const header = lines[0];
  if (header !== CSV_HEADER) {
    throw new Error(`Unexpected header. Expected: ${CSV_HEADER}`);
  }

  return lines.slice(1).map((line) => {
    const [email, user_code, password, department, batch, semester] = line.split(",").map((c) => c.trim());
    return {
      email,
      user_code,
      password,
      department,
      batch,
      semester: Number(semester) || 1,
    };
  });
}

async function submitRows(rows: StudentRow[]): Promise<BulkCreateResult> {
  return api.post<BulkCreateResult>("/api/v1/auth/users/bulk/", { rows });
}

/** Read a File's text via FileReader rather than the Blob.text() method —
 * jsdom (used in tests) doesn't implement File.text(), and FileReader has
 * broader real-world browser support anyway. */
function readFileAsText(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("Failed to read file."));
    reader.readAsText(file);
  });
}

function AddStudentForm({ onResult }: { onResult: (r: BulkCreateResult) => void }) {
  const [email, setEmail] = useState("");
  const [userCode, setUserCode] = useState("");
  const [password, setPassword] = useState("");
  const [department, setDepartment] = useState("");
  const [batch, setBatch] = useState("");
  const [semester, setSemester] = useState("1");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const onSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setSubmitting(true);
      setError(null);
      setSuccess(null);
      try {
        const result = await submitRows([
          {
            email,
            user_code: userCode,
            password,
            department,
            batch,
            semester: Number(semester) || 1,
          },
        ]);
        onResult(result);
        if (result.failed.length > 0) {
          setError(result.failed[0].error);
        } else {
          setSuccess(`Created ${result.created[0]?.email ?? email}.`);
          setEmail("");
          setUserCode("");
          setPassword("");
          setDepartment("");
          setBatch("");
          setSemester("1");
        }
      } catch (err) {
        setError(errMsg(err));
      } finally {
        setSubmitting(false);
      }
    },
    [email, userCode, password, department, batch, semester, onResult],
  );

  return (
    <Card>
      <CardHeader title="Add one student" />
      <CardBody>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Field label="Email" htmlFor="add-student-email">
              <Input
                id="add-student-email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </Field>
            <Field label="User code" htmlFor="add-student-code">
              <Input
                id="add-student-code"
                required
                value={userCode}
                onChange={(e) => setUserCode(e.target.value)}
                placeholder="e.g. STU001"
              />
            </Field>
            <Field label="Password" htmlFor="add-student-password">
              <Input
                id="add-student-password"
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Field label="Department" htmlFor="add-student-department">
              <Input
                id="add-student-department"
                required
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
              />
            </Field>
            <Field label="Batch" htmlFor="add-student-batch">
              <Input
                id="add-student-batch"
                required
                value={batch}
                onChange={(e) => setBatch(e.target.value)}
                placeholder="e.g. 2026"
              />
            </Field>
            <Field label="Semester" htmlFor="add-student-semester">
              <Input
                id="add-student-semester"
                type="number"
                min={1}
                required
                value={semester}
                onChange={(e) => setSemester(e.target.value)}
              />
            </Field>
          </div>
          {error && <Alert tone="error">{error}</Alert>}
          {success && <Alert tone="success">{success}</Alert>}
          <Button type="submit" loading={submitting}>
            Add student
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}

function BulkStudentUpload({ onResult }: { onResult: (r: BulkCreateResult) => void }) {
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const onFileChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      e.target.value = ""; // allow re-selecting the same file after a failed attempt
      if (!file) return;

      setError(null);
      let rows: StudentRow[];
      try {
        const text = await readFileAsText(file);
        rows = parseStudentCsv(text);
      } catch (err) {
        setError(errMsg(err));
        return;
      }
      if (rows.length === 0) {
        setError("CSV file has no data rows.");
        return;
      }

      setUploading(true);
      try {
        const result = await submitRows(rows);
        onResult(result);
      } catch (err) {
        setError(errMsg(err));
      } finally {
        setUploading(false);
      }
    },
    [onResult],
  );

  return (
    <Card>
      <CardHeader title="Bulk upload (CSV)" />
      <CardBody>
        <div className="space-y-4">
          <p className="text-[13px] text-muted">
            Columns: <code>{CSV_HEADER}</code>.{" "}
            <a href="/sample-student-upload.csv" className="text-primary underline" download>
              Download sample CSV
            </a>
          </p>
          <Field label="CSV file" htmlFor="bulk-student-csv">
            <input
              id="bulk-student-csv"
              type="file"
              accept=".csv"
              onChange={onFileChange}
              disabled={uploading}
              className="block w-full text-[13px] text-muted file:mr-3 file:rounded-md file:border-0 file:bg-primary file:px-3 file:py-1.5 file:text-primary-fg"
            />
          </Field>
          {uploading && <p className="text-[13px] text-muted">Uploading…</p>}
          {error && <Alert tone="error">{error}</Alert>}
        </div>
      </CardBody>
    </Card>
  );
}

function BulkResultsPanel({ result }: { result: BulkCreateResult | null }) {
  if (result === null) return null;
  return (
    <Card>
      <CardHeader title={`Results: ${result.created.length} created, ${result.failed.length} failed`} />
      <CardBody>
        <p className="mb-3 text-[13px] text-muted">
          Created students&apos; profiles (department/batch/semester) sync in the background — they may take a
          few seconds to appear.
        </p>
        <Table>
          <THead>
            <HeaderRow>
              <TH>Row</TH>
              <TH>Email</TH>
              <TH>Status</TH>
            </HeaderRow>
          </THead>
          <TBody>
            {result.created.map((c) => (
              <Row key={`created-${c.row}`}>
                <TD>{c.row + 1}</TD>
                <TD className="font-medium">{c.email}</TD>
                <TD>
                  <StatusPill status="Created" tone="success" />
                </TD>
              </Row>
            ))}
            {result.failed.map((f) => (
              <Row key={`failed-${f.row}`}>
                <TD>{f.row + 1}</TD>
                <TD className="font-medium">{f.email}</TD>
                <TD>
                  <span className="text-danger">{f.error}</span>
                </TD>
              </Row>
            ))}
          </TBody>
        </Table>
      </CardBody>
    </Card>
  );
}

function AddStudentsContent() {
  const [result, setResult] = useState<BulkCreateResult | null>(null);

  return (
    <div className="space-y-6">
      <AddStudentForm onResult={setResult} />
      <BulkStudentUpload onResult={setResult} />
      <BulkResultsPanel result={result} />
    </div>
  );
}

export default function AddStudentsPage() {
  return (
    <DashboardShell title="Add Students" role="admin">
      <AddStudentsContent />
    </DashboardShell>
  );
}
