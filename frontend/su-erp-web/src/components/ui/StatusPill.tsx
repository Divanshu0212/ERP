import { cn } from "@/lib/cn";

// Map a domain status string to a semantic tone. Kept generous so the same
// pill serves invoices, allocations, grievances, and institution flags.
type Tone = "neutral" | "success" | "warn" | "danger" | "info";

const TONES: Record<Tone, string> = {
  neutral: "bg-surface-2 text-muted ring-line",
  success: "bg-success/10 text-success ring-success/25",
  warn: "bg-warn/10 text-warn ring-warn/25",
  danger: "bg-danger/10 text-danger ring-danger/25",
  info: "bg-primary/10 text-primary ring-primary/25",
};

const STATUS_TONE: Record<string, Tone> = {
  // positive / terminal-good
  confirmed: "success",
  paid: "success",
  active: "success",
  success: "success",
  settled: "success",
  // in-flight
  pending: "warn",
  processing: "warn",
  scored: "info",
  // terminal-bad
  failed: "danger",
  released: "danger",
  cancelled: "danger",
  escalated: "danger",
  critical: "danger",
  high: "danger",
  // urgency-ish
  medium: "warn",
  low: "neutral",
};

function toneFor(status: string): Tone {
  return STATUS_TONE[status.toLowerCase()] ?? "neutral";
}

/**
 * A small status chip. Pass a domain `status` to auto-map its color, or an
 * explicit `tone`. Boolean-ish flags read best as `active`/`inactive`.
 */
export function StatusPill({
  status,
  tone,
  className,
}: {
  status: string;
  tone?: Tone;
  className?: string;
}) {
  const resolved = tone ?? toneFor(status);
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium capitalize ring-1 ring-inset",
        TONES[resolved],
        className,
      )}
    >
      {status}
    </span>
  );
}
