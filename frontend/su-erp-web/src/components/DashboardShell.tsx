"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Building2,
  CreditCard,
  GraduationCap,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageSquareWarning,
  Bus,
  UtensilsCrossed,
  User,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { api } from "@/lib/api";
import { clearToken } from "@/lib/auth";
import type { TokenClaims } from "@/lib/auth";
import { fetchMe } from "@/lib/session";
import type { MeResponse } from "@/lib/session";
import { useAuthGuard } from "@/lib/useAuthGuard";
import { cn } from "@/lib/cn";
import { Avatar, Monogram } from "@/components/ui/Monogram";

import type { ReactNode } from "react";

interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
}

// Nav is role-scoped and only links to pages that exist.
const NAV: Record<string, NavItem[]> = {
  student: [
    { label: "Overview", href: "/student", icon: LayoutDashboard },
    { label: "Canteen", href: "/canteen", icon: UtensilsCrossed },
    { label: "Pay & confirm", href: "/student/saga-demo", icon: CreditCard },
    { label: "Raise grievance", href: "/student/escalation-demo", icon: MessageSquareWarning },
    { label: "Profile", href: "/student/profile", icon: User },
  ],
  warden: [
    { label: "Overview", href: "/warden", icon: LayoutDashboard },
    { label: "Profile", href: "/warden/profile", icon: User },
  ],
  admin: [
    { label: "Overview", href: "/admin", icon: LayoutDashboard },
    { label: "Add Students", href: "/admin/students/new", icon: GraduationCap },
    { label: "Users", href: "/admin/users", icon: User },
    { label: "Profile", href: "/admin/profile", icon: User },
  ],
  superadmin: [{ label: "Institutions", href: "/superadmin", icon: Building2 }],
  faculty: [
    { label: "Overview", href: "/faculty", icon: GraduationCap },
    { label: "Profile", href: "/faculty/profile", icon: User },
  ],
  driver: [
    { label: "My schedules", href: "/driver", icon: Bus },
    { label: "Profile", href: "/driver/profile", icon: User },
  ],
  canteen_owner: [
    { label: "Canteen", href: "/canteen-owner", icon: UtensilsCrossed },
    { label: "Profile", href: "/canteen-owner/profile", icon: User },
  ],
};

interface Institution {
  name: string;
  slug: string;
  id: string;
}

/**
 * Application shell: a persistent role-aware sidebar and a top bar carrying the
 * institution monogram, plus the guarded content region. Keeps the original
 * `DashboardShell` contract (title, role, render-prop children with claims) so
 * pages need no change.
 */
export function DashboardShell({
  title,
  role,
  children,
}: {
  title: string;
  role: string;
  children?: ReactNode | ((claims: TokenClaims) => ReactNode);
}) {
  const { ready, claims } = useAuthGuard(role);
  const router = useRouter();
  const pathname = usePathname();
  const [institution, setInstitution] = useState<Institution | null>(null);
  const [me, setMe] = useState<MeResponse | null>(null);
  const [navOpen, setNavOpen] = useState(false);

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    api
      .get<Institution>("/api/v1/auth/institution")
      .then((data) => {
        if (!cancelled) setInstitution(data);
      })
      .catch(() => {
        // Non-fatal: the topbar falls back to a generic label.
      });
    fetchMe()
      .then((data) => {
        if (!cancelled) setMe(data);
      })
      .catch(() => {
        // Non-fatal: the avatar falls back to the user_code label.
      });
    return () => {
      cancelled = true;
    };
  }, [ready]);

  if (!ready) {
    return (
      <main className="flex min-h-screen items-center justify-center text-sm text-muted">
        Loading…
      </main>
    );
  }

  const body =
    typeof children === "function" ? (claims ? children(claims) : null) : children;

  const items = NAV[role] ?? [];
  const instName = institution?.name ?? "Institution";
  const instKey = claims?.tenant ?? institution?.id ?? instName;
  const avatarLabel = me?.email ?? claims?.sub ?? "user";

  function logout() {
    clearToken();
    router.replace("/login");
  }

  const sidebar = (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2.5 px-4 py-4">
        <span
          aria-hidden
          className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-fg"
        >
          <Building2 className="h-4 w-4" />
        </span>
        <span className="text-sm font-[650] tracking-tight text-ink">SU-ERP</span>
      </div>
      <nav className="flex-1 space-y-0.5 px-2 py-2">
        {items.map((item) => {
          const active = pathname === item.href;
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => setNavOpen(false)}
              className={cn(
                "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-[13px] font-medium transition-colors",
                active
                  ? "bg-primary/10 text-primary"
                  : "text-muted hover:bg-surface-2 hover:text-ink",
              )}
              aria-current={active ? "page" : undefined}
            >
              <Icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="border-t border-line px-3 py-3">
        <div className="mb-2 flex items-center gap-2.5 px-1">
          <Monogram name={instName} colorKey={instKey} size="sm" />
          <div className="min-w-0">
            <p className="truncate text-[11px] uppercase tracking-wide text-muted">Institution</p>
            <p className="truncate font-mono text-[12px] text-ink">{institution?.slug ?? "—"}</p>
          </div>
        </div>
        <button
          type="button"
          onClick={logout}
          className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-[13px] font-medium text-muted transition-colors hover:bg-surface-2 hover:text-ink"
        >
          <LogOut className="h-4 w-4" />
          Sign out
        </button>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-canvas lg:grid lg:grid-cols-[240px_1fr]">
      {/* Desktop sidebar */}
      <aside className="sticky top-0 hidden h-screen border-r border-line bg-surface lg:block">
        {sidebar}
      </aside>

      {/* Mobile drawer */}
      {navOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div
            className="absolute inset-0 bg-ink/30"
            onClick={() => setNavOpen(false)}
            aria-hidden
          />
          <aside className="absolute left-0 top-0 h-full w-64 border-r border-line bg-surface">
            {sidebar}
          </aside>
        </div>
      )}

      <div className="flex min-h-screen flex-col">
        <header className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-line bg-surface/95 px-4 py-3 backdrop-blur sm:px-6">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setNavOpen(true)}
              className="rounded-md p-1.5 text-muted hover:bg-surface-2 lg:hidden"
              aria-label="Open navigation"
            >
              <Menu className="h-5 w-5" />
            </button>
            <div className="flex items-center gap-2.5">
              <Monogram name={instName} colorKey={instKey} size="sm" />
              <span className="text-sm font-medium text-ink">{instName}</span>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="hidden text-[13px] capitalize text-muted sm:inline">{role}</span>
            <Avatar label={avatarLabel} size="sm" />
          </div>
        </header>

        <main className="mx-auto w-full max-w-6xl flex-1 space-y-6 px-4 py-6 sm:px-6 sm:py-8">
          <h1 className="text-[28px] font-[650] leading-tight tracking-tight text-ink">
            {title}
          </h1>
          {body}
        </main>
      </div>
    </div>
  );
}
