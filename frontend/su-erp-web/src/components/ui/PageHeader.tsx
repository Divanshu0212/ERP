import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * Page heading block: an uppercase eyebrow, a tight-tracked title, an optional
 * description, and an action slot pinned to the right.
 */
export function PageHeader({
  eyebrow,
  title,
  description,
  action,
  className,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between",
        className,
      )}
    >
      <div className="min-w-0">
        {eyebrow && (
          <p className="mb-1 text-eyebrow font-semibold uppercase text-muted">
            {eyebrow}
          </p>
        )}
        <h1 className="text-[28px] font-[650] leading-tight tracking-tight text-ink">
          {title}
        </h1>
        {description && (
          <p className="mt-1.5 max-w-2xl text-sm text-muted">{description}</p>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}
