"use client";

// Requires warden/admin login (locked design decision — receipt verification
// is a staff action, not a public one). `useAuthGuard` only supports a single
// exact expected role, so this page calls it with no expected role (any
// logged-in user passes the redirect-to-login check) and then gates on
// `claims.role` itself, sending non-warden/admin users to their own
// dashboard — the same "redirect elsewhere" behavior `useAuthGuard` would
// give for a single mismatched role, just covering two roles instead of one.

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { api, ApiError } from "@/lib/api";
import { useAuthGuard } from "@/lib/useAuthGuard";
import { dashboardPathForRole } from "@/lib/routes";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Alert } from "@/components/ui/Alert";

interface VerifyResult {
  valid: boolean;
  receipt_no?: string;
  amount?: string;
  purpose?: string;
  university_name?: string;
  paid_on?: string;
}

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return e instanceof Error ? e.message : "Something went wrong.";
}

function VerifyReceiptContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const [result, setResult] = useState<VerifyResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) {
      setError("No verification token provided.");
      setLoading(false);
      return;
    }
    api
      .post<VerifyResult>("/api/v1/finance/receipts/verify", { token })
      .then(setResult)
      .catch((err) => setError(errMsg(err)))
      .finally(() => setLoading(false));
  }, [token]);

  return (
    <div className="mx-auto max-w-md">
      <Card>
        <CardHeader title="Receipt verification" />
        <CardBody>
          {loading && <p className="text-[13px] text-muted">Verifying…</p>}
          {error && <Alert tone="error">{error}</Alert>}
          {result && !result.valid && (
            <Alert tone="error">Invalid or unrecognized receipt.</Alert>
          )}
          {result && result.valid && (
            <div className="space-y-2 text-sm">
              <Alert tone="success">Valid receipt.</Alert>
              <p>
                <span className="text-muted">Receipt No:</span> {result.receipt_no}
              </p>
              <p>
                <span className="text-muted">University:</span> {result.university_name}
              </p>
              <p>
                <span className="text-muted">Purpose:</span> {result.purpose}
              </p>
              <p>
                <span className="text-muted">Amount:</span> {result.amount}
              </p>
              <p>
                <span className="text-muted">Paid On:</span>{" "}
                {result.paid_on && new Date(result.paid_on).toLocaleString()}
              </p>
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

export default function VerifyReceiptPage() {
  const { ready, claims } = useAuthGuard();
  const router = useRouter();

  useEffect(() => {
    if (!ready || !claims) return;
    if (claims.role !== "warden" && claims.role !== "admin") {
      router.replace(dashboardPathForRole(claims.role));
    }
  }, [ready, claims, router]);

  if (!ready || !claims || (claims.role !== "warden" && claims.role !== "admin")) {
    return (
      <main className="flex min-h-screen items-center justify-center text-sm text-muted">
        Loading…
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-canvas px-4 py-10 sm:px-6">
      <Suspense
        fallback={<p className="text-center text-[13px] text-muted">Loading…</p>}
      >
        <VerifyReceiptContent />
      </Suspense>
    </main>
  );
}
