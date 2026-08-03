#!/usr/bin/env bash
# Expose the local gateway to the internet through a Cloudflare tunnel.
#
# Why: the phone can only reach `localhost:8080` while it is plugged into this
# machine over `adb reverse`. A tunnel gives the same gateway a public HTTPS
# hostname, so the app works from mobile data, someone else's Wi-Fi, or a
# demo on a device that was never plugged in.
#
# Two modes:
#
#   quick (default)  No account, no domain, no setup. Cloudflare hands out a
#                    random *.trycloudflare.com hostname. It CHANGES every
#                    time this script restarts, which is why the URL is
#                    written to infra/tunnel-url.txt for the app to pick up.
#
#   named            A stable hostname on a domain you own. Requires a
#                    Cloudflare account, a domain on it, and a one-time
#                    `cloudflared tunnel login`. The tunnel itself is free.
#                    Set TUNNEL_NAME and TUNNEL_HOSTNAME to use it.
#
# The gateway is not authenticated by the tunnel — every service still
# verifies its own JWT (zero-trust), which is what makes exposing it
# acceptable. It does mean anyone with the URL can reach the login endpoint,
# so treat a quick-tunnel URL as semi-public and stop the tunnel when done.
#
# Usage:
#   ./scripts/tunnel.sh                     # quick tunnel
#   TUNNEL_NAME=suerp TUNNEL_HOSTNAME=api.example.com ./scripts/tunnel.sh
#
# Stop with Ctrl-C. See also: ./scripts/server.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATEWAY_URL="${GATEWAY_URL:-http://localhost:8080}"
URL_FILE="$REPO_ROOT/infra/tunnel-url.txt"
LOG_FILE="$REPO_ROOT/infra/tunnel.log"

if ! command -v cloudflared >/dev/null 2>&1; then
    cat >&2 <<'EOF'
cloudflared is not installed.

  Arch/CachyOS:  sudo pacman -S cloudflared
  Debian/Ubuntu: see https://pkg.cloudflare.com
  macOS:         brew install cloudflared
EOF
    exit 1
fi

# A tunnel to a dead gateway produces a public URL that 502s, which is a
# confusing thing to hand someone. Check first.
if ! curl -fsS --max-time 5 "$GATEWAY_URL/health" >/dev/null 2>&1; then
    echo "The gateway is not answering at $GATEWAY_URL/health." >&2
    echo "Start the stack first:  ./scripts/server.sh up" >&2
    exit 1
fi

echo "Gateway is up at $GATEWAY_URL"

# --- named tunnel -----------------------------------------------------------
# Stable hostname, survives restarts. Nothing to write to URL_FILE because the
# hostname never changes — put it in mobile/su-erp-app/.env once.
if [[ -n "${TUNNEL_NAME:-}" && -n "${TUNNEL_HOSTNAME:-}" ]]; then
    echo "Starting named tunnel '$TUNNEL_NAME' -> https://$TUNNEL_HOSTNAME"
    echo "https://$TUNNEL_HOSTNAME" > "$URL_FILE"
    echo
    echo "Set this in mobile/su-erp-app/.env (once — it is stable):"
    echo "  EXPO_PUBLIC_API_TUNNEL_URL=https://$TUNNEL_HOSTNAME"
    echo
    exec cloudflared tunnel run --url "$GATEWAY_URL" "$TUNNEL_NAME"
fi

# --- quick tunnel -----------------------------------------------------------
# cloudflared prints the assigned hostname to stderr a second or two after
# start. Tee the output so it is both visible and greppable for that URL.
echo "Starting quick tunnel (random hostname, changes on every restart)..."
: > "$LOG_FILE"

cloudflared tunnel --url "$GATEWAY_URL" --no-autoupdate > "$LOG_FILE" 2>&1 &
TUNNEL_PID=$!

cleanup() {
    kill "$TUNNEL_PID" 2>/dev/null || true
    rm -f "$URL_FILE"
    echo
    echo "Tunnel stopped."
}
trap cleanup EXIT INT TERM

# Wait for the hostname to appear rather than sleeping a fixed guess.
PUBLIC_URL=""
for _ in $(seq 1 30); do
    PUBLIC_URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG_FILE" | head -1 || true)"
    [[ -n "$PUBLIC_URL" ]] && break
    # The process dying is more informative than waiting out the full timeout.
    if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
        echo "cloudflared exited before printing a URL:" >&2
        tail -20 "$LOG_FILE" >&2
        exit 1
    fi
    sleep 1
done

if [[ -z "$PUBLIC_URL" ]]; then
    echo "Timed out waiting for a tunnel URL. Last output:" >&2
    tail -20 "$LOG_FILE" >&2
    exit 1
fi

echo "$PUBLIC_URL" > "$URL_FILE"

# Prove the whole path works before claiming success — a URL that exists but
# does not route is worse than no URL, because it looks fine.
if curl -fsS --max-time 15 "$PUBLIC_URL/health" >/dev/null 2>&1; then
    REACHABLE="verified"
else
    REACHABLE="NOT yet answering (edge propagation can take a few seconds)"
fi

cat <<EOF

  Tunnel:  $PUBLIC_URL
  Health:  $REACHABLE
  Written: infra/tunnel-url.txt

Point the app at it:

  cd mobile/su-erp-app
  echo "EXPO_PUBLIC_API_TUNNEL_URL=$PUBLIC_URL" >> .env
  npx expo start --clear      # .env is read at bundle time

The app probes this URL first and falls back to EXPO_PUBLIC_API_BASE_URL
(localhost) automatically when the tunnel is down.

Ctrl-C to stop.
EOF

wait "$TUNNEL_PID"
