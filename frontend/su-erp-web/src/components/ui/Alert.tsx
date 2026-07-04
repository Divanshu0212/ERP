import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

type Tone = "info" | "success" | "error";

const TONES: Record<Tone, string> = {
  info: "border-primary/30 bg-primary/5 text-ink",
  success: "border-success/30 bg-success/5 text-ink",
  error: "border-danger/30 bg-danger/5 text-ink",
};

/**
 * An inline message tied to an action's result. Errors state what happened and,
 * where possible, how to fix it — they don't apologize. `role` is alert for
 * errors (assertive) and status otherwise.
 */
export function Alert({
  tone = "info",
  children,
  className,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={cn(
        "rounded-md border px-3 py-2 text-[13px]",
        TONES[tone],
        className,
      )}
    >
      {children}
    </div>
  );
}
