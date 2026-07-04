// Tiny className joiner. Filters falsy values and joins with spaces.
// Avoids a runtime dependency on clsx/tailwind-merge for a one-liner need.

export type ClassValue = string | number | false | null | undefined;

export function cn(...values: ClassValue[]): string {
  return values.filter(Boolean).join(" ");
}
