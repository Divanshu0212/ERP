import { cn } from "@/lib/cn";
import { initialsFromName, initialsFromEmail, tenantColor } from "./tenant-color";

const SIZES = {
  sm: "h-7 w-7 text-[11px]",
  md: "h-9 w-9 text-xs",
  lg: "h-11 w-11 text-sm",
} as const;

type Size = keyof typeof SIZES;

/**
 * Institution monogram chip: a rounded square with two-letter initials on a
 * deterministic, tenant-colored background. `colorKey` should be the stable
 * tenant identity (UUID or slug); it falls back to the name.
 */
export function Monogram({
  name,
  colorKey,
  size = "md",
  className,
}: {
  name: string;
  colorKey?: string;
  size?: Size;
  className?: string;
}) {
  const { bg, fg } = tenantColor(colorKey || name);
  return (
    <span
      aria-hidden
      style={{ backgroundColor: bg, color: fg }}
      className={cn(
        "inline-flex select-none items-center justify-center rounded-md font-semibold tracking-wide",
        SIZES[size],
        className,
      )}
    >
      {initialsFromName(name)}
    </span>
  );
}

/**
 * User avatar: a circular chip with initials from an email address. Uses the
 * same deterministic color logic keyed on the email so a person keeps a stable
 * color.
 */
export function Avatar({
  email,
  size = "md",
  className,
}: {
  email: string;
  size?: Size;
  className?: string;
}) {
  const { bg, fg } = tenantColor(email);
  return (
    <span
      aria-hidden
      style={{ backgroundColor: bg, color: fg }}
      className={cn(
        "inline-flex select-none items-center justify-center rounded-full font-semibold",
        SIZES[size],
        className,
      )}
    >
      {initialsFromEmail(email)}
    </span>
  );
}
