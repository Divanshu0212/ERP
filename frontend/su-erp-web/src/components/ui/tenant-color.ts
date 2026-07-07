// Deterministic tenant color: hash a stable tenant key (UUID / slug / name) to a
// hue in a tasteful band, with fixed saturation + lightness so every monogram
// reads as on-brand regardless of the institution. This visually encodes
// multi-tenancy — the memorable signature detail of the UI.

/** FNV-1a: small, stable, non-crypto string hash. */
function hashString(input: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/**
 * A muted, well-saturated background + solid light foreground for a tenant
 * monogram. Hue spans the full wheel; saturation/lightness are pinned so the
 * result always looks deliberate rather than random.
 */
export function tenantColor(key: string): { bg: string; fg: string } {
  const hue = hashString(key || "institution") % 360;
  return {
    bg: `hsl(${hue} 42% 34%)`,
    fg: "hsl(0 0% 100%)",
  };
}

/** Two-letter initials from an institution name (or any label). */
export function initialsFromName(name: string): string {
  const words = (name || "").trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "··";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[words.length - 1][0]).toUpperCase();
}

/** Initials from an email address (local part), for user avatars. */
export function initialsFromEmail(email: string): string {
  const local = (email || "").split("@")[0] || "";
  const parts = local.split(/[.\-_+]/).filter(Boolean);
  if (parts.length === 0) return (email || "?").slice(0, 2).toUpperCase();
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

/** Two-letter initials from any freeform label (name, user_code, etc.),
 * falling back to `initialsFromEmail` semantics when the label contains "@". */
export function initialsFromLabel(label: string): string {
  if (label.includes("@")) return initialsFromEmail(label);
  const cleaned = (label || "").trim();
  if (!cleaned) return "?";
  return cleaned.slice(0, 2).toUpperCase();
}
