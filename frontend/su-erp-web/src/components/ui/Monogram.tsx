import { cn } from "@/lib/cn";
import { initialsFromName, initialsFromLabel, tenantColor } from "./tenant-color";

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
 * User avatar: shows the profile photo if `photoUrl` is set, else a circular
 * chip with initials derived from `label` (typically the user's real email;
 * falls back gracefully for any other label shape). Uses the same
 * deterministic color logic keyed on `label` so a person keeps a stable color.
 */
export function Avatar({
  label,
  photoUrl,
  size = "md",
  className,
}: {
  label: string;
  photoUrl?: string;
  size?: Size;
  className?: string;
}) {
  const { bg, fg } = tenantColor(label);
  if (photoUrl) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={photoUrl}
        alt=""
        className={cn("inline-block rounded-full object-cover", SIZES[size], className)}
      />
    );
  }
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
      {initialsFromLabel(label)}
    </span>
  );
}
