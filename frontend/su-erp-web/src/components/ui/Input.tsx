import { forwardRef } from "react";
import type { InputHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

const CONTROL =
  "w-full rounded-md border border-line bg-surface px-3 text-sm text-ink " +
  "placeholder:text-muted shadow-subtle transition-colors " +
  "focus:border-primary focus:outline-none focus-visible:ring-2 " +
  "focus-visible:ring-primary/40 disabled:cursor-not-allowed disabled:opacity-60";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...rest }, ref) {
    return <input ref={ref} className={cn(CONTROL, "h-10", className)} {...rest} />;
  },
);
