"use client";

import { useEffect, useState } from "react";

import { DashboardShell } from "@/components/DashboardShell";
import { api, ApiError } from "@/lib/api";
import { listItems } from "@/lib/paginate";
import { cn } from "@/lib/cn";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Alert } from "@/components/ui/Alert";
import { EmptyState } from "@/components/ui/EmptyState";
import { StatusPill } from "@/components/ui/StatusPill";
import { Monogram } from "@/components/ui/Monogram";
import { Table, TBody, TD, TH, THead, HeaderRow, Row } from "@/components/ui/Table";

interface Institution {
  id: string;
  slug: string;
  name: string;
  is_active: boolean;
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

/** Turn a display name into a URL-safe slug suggestion. */
function slugify(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

function SuperadminContent() {
  const [institutions, setInstitutions] = useState<Institution[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  async function loadInstitutions() {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await api.get("/api/v1/auth/institutions");
      setInstitutions(listItems<Institution>(data));
    } catch (e) {
      setLoadError(errMsg(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadInstitutions();
  }, []);

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-2">
        <CreateInstitution onCreated={loadInstitutions} />
        <CreateAdmin institutions={institutions} />
      </div>

      <Card>
        <CardHeader title={`Institutions${institutions.length ? ` (${institutions.length})` : ""}`} />
        {loading ? (
          <p role="status" className="p-4 text-[13px] text-muted">
            Loading…
          </p>
        ) : loadError ? (
          <p role="alert" className="p-4 text-[13px] text-danger">
            {loadError}
          </p>
        ) : institutions.length === 0 ? (
          <EmptyState
            title="No institutions yet"
            description="Create the first institution above, then provision its admin."
          />
        ) : (
          <Table>
            <THead>
              <HeaderRow>
                <TH>Institution</TH>
                <TH>Slug</TH>
                <TH>Status</TH>
                <TH>Created</TH>
              </HeaderRow>
            </THead>
            <TBody>
              {institutions.map((inst) => (
                <Row key={inst.id}>
                  <TD>
                    <div className="flex items-center gap-2.5">
                      <Monogram name={inst.name} colorKey={inst.id} size="sm" />
                      <span className="font-medium">{inst.name}</span>
                    </div>
                  </TD>
                  <TD className="font-mono text-muted">{inst.slug}</TD>
                  <TD>
                    <StatusPill status={inst.is_active ? "active" : "inactive"} />
                  </TD>
                  <TD className="text-muted">{fmtDate(inst.created_at)}</TD>
                </Row>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </div>
  );
}

function CreateInstitution({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  function onNameChange(v: string) {
    setName(v);
    if (!slugEdited) setSlug(slugify(v));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    setOk(null);
    try {
      const created = await api.post<Institution>("/api/v1/auth/institutions", { slug, name });
      setOk(`Created ${created.name}.`);
      setName("");
      setSlug("");
      setSlugEdited(false);
      onCreated();
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <Card as="form" className="flex flex-col">
      <CardHeader title="Create institution" />
      <CardBody className="space-y-4">
        <Field label="Name" htmlFor="inst-name">
          <Input
            id="inst-name"
            value={name}
            onChange={(e) => onNameChange(e.target.value)}
            placeholder="Riverside Institute of Technology"
            required
          />
        </Field>
        <Field label="Slug" htmlFor="inst-slug" hint="Used at sign-in and in URLs.">
          <Input
            id="inst-slug"
            value={slug}
            onChange={(e) => {
              setSlug(e.target.value);
              setSlugEdited(true);
            }}
            placeholder="riverside-tech"
            required
          />
        </Field>
        {error && <Alert tone="error">{error}</Alert>}
        {ok && <Alert tone="success">{ok}</Alert>}
        <div>
          <Button type="submit" loading={pending} onClick={submit}>
            Create institution
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}

function CreateAdmin({ institutions }: { institutions: Institution[] }) {
  const [slug, setSlug] = useState("");
  const [email, setEmail] = useState("");
  const [userCode, setUserCode] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    setOk(null);
    try {
      await api.post("/api/v1/auth/admins", {
        institution_slug: slug,
        email,
        user_code: userCode,
        password,
      });
      setOk(`Admin ${email} added.`);
      setEmail("");
      setUserCode("");
      setPassword("");
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setPending(false);
    }
  }

  const disabled = institutions.length === 0;

  return (
    <Card as="form" className="flex flex-col">
      <CardHeader title="Add institution admin" />
      <CardBody className="space-y-4">
        <Field label="Institution" htmlFor="admin-inst">
          <Select
            id="admin-inst"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            required
            disabled={disabled}
          >
            <option value="" disabled>
              {disabled ? "Create an institution first" : "Select an institution"}
            </option>
            {institutions.map((inst) => (
              <option key={inst.id} value={inst.slug}>
                {inst.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Admin email" htmlFor="admin-email">
          <Input
            id="admin-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="admin@riverside.edu"
            required
          />
        </Field>
        <Field label="User code" htmlFor="admin-user-code">
          <Input
            id="admin-user-code"
            value={userCode}
            onChange={(e) => setUserCode(e.target.value)}
            required
          />
        </Field>
        <Field label="Temporary password" htmlFor="admin-pass">
          <Input
            id="admin-pass"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </Field>
        {error && <Alert tone="error">{error}</Alert>}
        {ok && <Alert tone="success">{ok}</Alert>}
        <div>
          <Button type="submit" loading={pending} onClick={submit} disabled={disabled}>
            Add admin
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}

export default function SuperadminPage() {
  return (
    <DashboardShell title="Institutions" role="superadmin">
      <div className={cn("space-y-6")}>
        <p className="max-w-2xl text-sm text-muted">
          Provision the institutions that run on the platform and their first
          administrators. Each admin manages their own institution&rsquo;s users.
        </p>
        <SuperadminContent />
      </div>
    </DashboardShell>
  );
}
