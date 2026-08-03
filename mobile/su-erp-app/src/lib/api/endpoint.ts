/**
 * Where the gateway is, decided at runtime rather than at build time.
 *
 * The app has to reach the same backend from two very different places: a
 * Cloudflare tunnel when the phone is on mobile data or someone else's Wi-Fi,
 * and `localhost:8080` over `adb reverse` when it is plugged into the dev
 * machine. Neither is right all the time, and a quick tunnel's hostname
 * changes every time `cloudflared` restarts — so baking one URL into `.env`
 * means editing it and restarting Metro every time the situation changes.
 *
 * Instead: probe the candidates, keep the first that answers, and re-probe
 * when a request fails. The tunnel is listed first because it works from
 * anywhere; localhost is the fallback that works when the tunnel is down.
 */

/** Long enough for a tunnel round-trip, short enough not to stall launch. */
const PROBE_TIMEOUT_MS = 3_000;

/**
 * The gateway's own liveness endpoint (nginx.conf `location = /health`),
 * unauthenticated and served without touching a backend. Any response at all
 * proves something is listening, which is the only question being asked here.
 */
const PROBE_PATH = '/health';

function envCandidates(): string[] {
  const tunnel = process.env.EXPO_PUBLIC_API_TUNNEL_URL;
  const local = process.env.EXPO_PUBLIC_API_BASE_URL ?? 'http://localhost:8080';

  // Tunnel first: it is the one that works off the dev machine's network.
  // Deduplicated so an unset tunnel var does not probe localhost twice.
  return [...new Set([tunnel, local].filter((url): url is string => Boolean(url)))];
}

export let CANDIDATES: string[] = envCandidates();

/**
 * A stable URL holding the *current* gateway address as plain text.
 *
 * This exists for the installed APK. `EXPO_PUBLIC_*` values are compiled into
 * the bundle at build time, so an APK built against a quick tunnel points at a
 * hostname that dies the next time `cloudflared` restarts — and `localhost` is
 * meaningless on a phone that is not plugged in, so the app would have no way
 * back. Publishing the live URL somewhere stable (a GitHub gist, a pinned
 * file, any static host) lets a shipped build re-find the server without
 * being rebuilt.
 *
 * Unset by default: it costs a round-trip and is only consulted when every
 * baked-in candidate is already dead.
 */
let discoveryUrl: string | undefined = process.env.EXPO_PUBLIC_API_DISCOVERY_URL;

/** The endpoint currently believed good. Null until the first probe lands. */
let resolved: string | null = null;
/** Concurrent callers share one probe rather than starting a race each. */
let inFlight: Promise<string> | null = null;

/**
 * The best URL known right now, without waiting.
 *
 * Callers that cannot be async (module-level constants, download helpers that
 * build a URL synchronously) use this. Before the first probe resolves it is
 * the first candidate, which is the same guess the old build-time constant
 * made — so this is never worse than what it replaced.
 */
export function currentBaseUrl(): string {
  return resolved ?? CANDIDATES[0];
}

async function answers(origin: string): Promise<boolean> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);

  try {
    await fetch(`${origin}${PROBE_PATH}`, { method: 'GET', signal: controller.signal });
    return true;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Ask the discovery URL where the gateway moved to. Never throws — a failed
 * lookup just means the caller falls through to its own fallback.
 */
async function discover(): Promise<string | null> {
  if (!discoveryUrl) return null;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);

  try {
    const response = await fetch(discoveryUrl, { signal: controller.signal });
    if (!response.ok) return null;

    const candidate = (await response.text()).trim();
    // Anything that is not an http(s) origin is a stale file, an HTML error
    // page, or a typo — none of which should become a base URL.
    if (!/^https?:\/\/\S+$/.test(candidate)) return null;

    return (await answers(candidate)) ? candidate : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

async function probe(): Promise<string> {
  for (const candidate of CANDIDATES) {
    if (await answers(candidate)) {
      resolved = candidate;
      return candidate;
    }
  }

  // Every baked-in address is dead. In a shipped APK that usually means the
  // tunnel was restarted with a new hostname, which discovery can recover
  // from; in dev it means the stack is down, and discovery is unset anyway.
  const discovered = await discover();
  if (discovered) {
    resolved = discovered;
    return discovered;
  }

  // Nothing answered. That usually means the phone is offline, not that the
  // config is wrong — so return a usable URL and let the request fail into
  // the offline queue, which is the behaviour the rest of the app expects.
  return CANDIDATES[0];
}

/** Resolve the gateway origin, probing only when the answer is unknown. */
export function resolveBaseUrl(): Promise<string> {
  if (resolved) return Promise.resolve(resolved);

  inFlight ??= probe().finally(() => {
    inFlight = null;
  });

  return inFlight;
}

/**
 * Forget the current endpoint so the next call re-probes.
 *
 * Called when a request could not reach the server: the tunnel may have been
 * restarted with a new hostname, or the phone may have been unplugged from
 * `adb reverse`. Re-probing is how the app follows that move without a
 * restart.
 */
export function invalidateBaseUrl(): void {
  resolved = null;
}

/** Test seam — resets module state and lets a test pin the candidate list. */
export function resetEndpointForTests(options?: {
  candidates?: string[];
  discoveryUrl?: string;
}): void {
  CANDIDATES = options?.candidates ?? envCandidates();
  discoveryUrl = options?.discoveryUrl;
  resolved = null;
  inFlight = null;
}
