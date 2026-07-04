import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * A single metric tile: a quiet label over a large tabular number, with
 * loading / error states so a failed count doesn't blank the row.
 */
export function StatCard({
  label,
  value,
  loading,
  error,
  icon,
  className,
}: {
  label: string;
  value: number | string | null;
  loading?: boolean;
  error?: string | null;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-md border border-line bg-surface p-4 shadow-subtle",
        className,
      )}
    >
      <div className="flex items-center justify-between">
        <p className="text-[13px] font-medium text-muted">{label}</p>
        {icon && <span className="text-muted">{icon}</span>}
      </div>
      {loading ? (
        <p role="status" className="mt-2 text-sm text-muted">
          Loading…
        </p>
      ) : error ? (
        <p role="alert" className="mt-2 text-sm text-danger">
          {error}
        </p>
      ) : (
        <p className="mt-2 text-3xl font-[650] tabular-nums tracking-tight text-ink">
          {value ?? "—"}
        </p>
      )}
    </div>
  );
}
