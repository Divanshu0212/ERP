"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Building2 } from "lucide-react";

import { login } from "@/lib/session";
import { Field } from "@/components/ui/Field";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Alert";

export default function LoginPage() {
  const router = useRouter();
  const [institutionSlug, setInstitutionSlug] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const { redirectTo } = await login(institutionSlug, email, password);
      router.replace(redirectTo);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Sign-in failed. Try again.";
      setError(message);
      setLoading(false);
    }
  }

  return (
    <main className="grid min-h-screen bg-canvas lg:grid-cols-2">
      {/* Brand panel */}
      <section className="relative hidden flex-col justify-between overflow-hidden bg-primary p-10 text-primary-fg lg:flex">
        <div className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-md bg-white/15">
            <Building2 className="h-5 w-5" />
          </span>
          <span className="text-lg font-[650] tracking-tight">SU-ERP</span>
        </div>
        <div className="max-w-md">
          <p className="text-eyebrow font-semibold uppercase text-white/70">
            University operations
          </p>
          <h1 className="mt-3 text-3xl font-[650] leading-tight tracking-tight text-balance">
            One console for admissions, hostel, fees, transport and grievances.
          </h1>
          <p className="mt-4 text-sm text-white/80">
            Every institution runs isolated on its own tenant. Sign in with your
            institution&rsquo;s handle to reach its workspace.
          </p>
        </div>
        <p className="text-[13px] text-white/60">Multi-tenant · event-driven · ML-assisted</p>
        <div
          aria-hidden
          className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-white/5"
        />
      </section>

      {/* Form panel */}
      <section className="flex items-center justify-center p-6 sm:p-10">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-2.5 lg:hidden">
            <span className="flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-fg">
              <Building2 className="h-5 w-5" />
            </span>
            <span className="text-lg font-[650] tracking-tight text-ink">SU-ERP</span>
          </div>

          <h2 className="text-2xl font-[650] tracking-tight text-ink">Sign in</h2>
          <p className="mt-1 text-sm text-muted">Use your institution handle and credentials.</p>

          <form onSubmit={handleSubmit} noValidate className="mt-6 space-y-4">
            <Field label="Institution" htmlFor="institutionSlug" hint="e.g. demo-univ">
              <Input
                id="institutionSlug"
                name="institutionSlug"
                type="text"
                autoComplete="organization"
                required
                value={institutionSlug}
                onChange={(e) => setInstitutionSlug(e.target.value)}
                placeholder="demo-univ"
              />
            </Field>

            <Field label="Email" htmlFor="email">
              <Input
                id="email"
                name="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </Field>

            <Field label="Password" htmlFor="password">
              <Input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>

            {error && <Alert tone="error">{error}</Alert>}

            <Button type="submit" loading={loading} className="w-full">
              {loading ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        </div>
      </section>
    </main>
  );
}
