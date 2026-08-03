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

async function probe(): Promise<string> {
  for (const candidate of CANDIDATES) {
    if (await answers(candidate)) {
      resolved = candidate;
      return candidate;
    }
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
export function resetEndpointForTests(options?: { candidates?: string[] }): void {
  CANDIDATES = options?.candidates ?? envCandidates();
  resolved = null;
  inFlight = null;
}
