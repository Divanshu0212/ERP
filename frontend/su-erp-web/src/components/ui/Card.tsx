import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

/** A quiet surface panel: hairline border, low shadow, restrained radius. */
export function Card({
  children,
  className,
  as: Tag = "div",
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "section" | "form" | "article";
}) {
  return (
    <Tag
      className={cn(
        "rounded-md border border-line bg-surface shadow-subtle",
        className,
      )}
    >
      {children}
    </Tag>
  );
}

/** Header row inside a Card: a section title with an optional action slot. */
export function CardHeader({
  title,
  action,
  className,
}: {
  title: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-3 border-b border-line px-4 py-3",
        className,
      )}
    >
      <h2 className="text-sm font-semibold text-ink">{title}</h2>
      {action}
    </div>
  );
}

/** Padded body region for a Card. */
export function CardBody({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={cn("p-4", className)}>{children}</div>;
}
