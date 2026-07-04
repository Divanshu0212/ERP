import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * Label + control + optional error/hint wrapper. Binds the label to the control
 * via `htmlFor`/`id` (pass the same `htmlFor` you give the control's `id`) and
 * exposes the error with role="alert".
 */
export function Field({
  label,
  htmlFor,
  error,
  hint,
  children,
  className,
}: {
  label: string;
  htmlFor: string;
  error?: string | null;
  hint?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("space-y-1.5", className)}>
      <label
        htmlFor={htmlFor}
        className="block text-[13px] font-medium text-ink"
      >
        {label}
      </label>
      {children}
      {hint && !error && <p className="text-xs text-muted">{hint}</p>}
      {error && (
        <p id={`${htmlFor}-error`} role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
    </div>
  );
}
