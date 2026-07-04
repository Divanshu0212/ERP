import { forwardRef } from "react";
import type { SelectHTMLAttributes } from "react";
import { ChevronDown } from "lucide-react";

import { cn } from "@/lib/cn";

const CONTROL =
  "h-10 w-full appearance-none rounded-md border border-line bg-surface pl-3 pr-9 " +
  "text-sm text-ink shadow-subtle transition-colors focus:border-primary " +
  "focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 " +
  "disabled:cursor-not-allowed disabled:opacity-60";

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className, children, ...rest }, ref) {
    return (
      <div className="relative">
        <select ref={ref} className={cn(CONTROL, className)} {...rest}>
          {children}
        </select>
        <ChevronDown
          aria-hidden
          className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted"
        />
      </div>
    );
  },
);
