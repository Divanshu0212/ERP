import type { ReactNode, ThHTMLAttributes, TdHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

/** Horizontally scrollable wrapper + base table. Zebra-free, hairline rows. */
export function Table({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className="overflow-x-auto">
      <table className={cn("w-full border-collapse text-left text-data", className)}>
        {children}
      </table>
    </div>
  );
}

export function THead({ children }: { children: ReactNode }) {
  return <thead>{children}</thead>;
}

export function TBody({ children }: { children: ReactNode }) {
  return <tbody>{children}</tbody>;
}

/** Header row: sits on a faint surface, muted uppercase-ish labels. */
export function HeaderRow({ children }: { children: ReactNode }) {
  return <tr className="border-b border-line bg-surface-2/60 text-muted">{children}</tr>;
}

/** Body row: hairline separator + hover highlight. */
export function Row({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <tr
      className={cn(
        "border-b border-line last:border-0 transition-colors hover:bg-surface-2/70",
        className,
      )}
    >
      {children}
    </tr>
  );
}

export function TH({
  children,
  className,
  ...rest
}: ThHTMLAttributes<HTMLTableCellElement> & { children?: ReactNode }) {
  return (
    <th
      scope="col"
      className={cn(
        "px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wide",
        className,
      )}
      {...rest}
    >
      {children}
    </th>
  );
}

export function TD({
  children,
  className,
  ...rest
}: TdHTMLAttributes<HTMLTableCellElement> & { children?: ReactNode }) {
  return (
    <td className={cn("px-4 py-2.5 align-middle text-ink", className)} {...rest}>
      {children}
    </td>
  );
}
