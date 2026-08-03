#!/usr/bin/env bash
# Run this machine as the SU-ERP server.
#
# Thin wrapper over docker compose that pins the compose file and the profile
# rules from CLAUDE.md, so bringing the stack up or down is one command that
# does not depend on remembering `-f infra/docker-compose.yml --profile full`.
#
# Profiles exist because this machine cannot run every service at once:
#   default        core + the eight demo services (what you want normally)
#   full           adds the stub services
#   observability  adds Prometheus + Grafana
#
# Usage:
#   ./scripts/server.sh up              # start (default profile)
#   ./scripts/server.sh up full         # start with the stub services too
#   ./scripts/server.sh down            # STOP AND REMOVE containers
#   ./scripts/server.sh stop            # stop, keep containers and data
#   ./scripts/server.sh restart
#   ./scripts/server.sh status
#   ./scripts/server.sh logs [service]
#   ./scripts/server.sh nuke            # down + DELETE ALL DATA (asks first)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/infra/docker-compose.yml"
GATEWAY_URL="${GATEWAY_URL:-http://localhost:8080}"

compose() {
    docker compose -f "$COMPOSE_FILE" "$@"
}

profile_args() {
    local profile="${1:-}"
    case "$profile" in
        ""|default) ;;
        full)          echo "--profile full" ;;
        observability) echo "--profile observability" ;;
        all)           echo "--profile full --profile observability" ;;
        *)
            echo "Unknown profile '$profile' (default|full|observability|all)" >&2
            exit 1
            ;;
    esac
}

wait_for_gateway() {
    printf 'Waiting for the gateway'
    for _ in $(seq 1 60); do
        if curl -fsS --max-time 2 "$GATEWAY_URL/health" >/dev/null 2>&1; then
            echo " — up at $GATEWAY_URL"
            return 0
        fi
        printf '.'
        sleep 2
    done
    echo
    echo "Gateway did not answer within 120s. Check: ./scripts/server.sh logs gateway" >&2
    return 1
}

CMD="${1:-}"
shift || true

case "$CMD" in
    up)
        # shellcheck disable=SC2046  # word splitting is the point here
        compose $(profile_args "${1:-}") up -d --build
        wait_for_gateway
        cat <<EOF

Stack is up.

  Gateway   $GATEWAY_URL
  Health    $GATEWAY_URL/health

Expose it to the internet:  ./scripts/tunnel.sh
Stop it:                    ./scripts/server.sh down
EOF
        ;;

    down)
        # Removes containers and the network, keeps named volumes — so
        # Postgres data survives. Use `nuke` to drop the data too.
        echo "Stopping and removing containers (data volumes are kept)..."
        compose --profile full --profile observability down
        echo "Down. Data volumes intact — ./scripts/server.sh up restores everything."
        ;;

    stop)
        # Leaves the containers in place, just not running. Faster to resume
        # than `down`, and keeps container-local state.
        compose --profile full --profile observability stop
        echo "Stopped. Resume with: ./scripts/server.sh up"
        ;;

    restart)
        compose --profile full --profile observability restart "$@"
        wait_for_gateway
        ;;

    status|ps)
        compose --profile full --profile observability ps
        echo
        if curl -fsS --max-time 3 "$GATEWAY_URL/health" >/dev/null 2>&1; then
            echo "Gateway: reachable at $GATEWAY_URL"
        else
            echo "Gateway: NOT reachable at $GATEWAY_URL"
        fi
        if [[ -f "$REPO_ROOT/infra/tunnel-url.txt" ]]; then
            echo "Tunnel:  $(cat "$REPO_ROOT/infra/tunnel-url.txt") (per infra/tunnel-url.txt)"
        else
            echo "Tunnel:  not running"
        fi
        ;;

    logs)
        compose --profile full --profile observability logs -f --tail=100 "$@"
        ;;

    nuke)
        # Destructive and not reversible: -v drops the named volumes, which is
        # every institution, user, invoice, and allocation in local Postgres.
        echo "This DELETES ALL LOCAL DATA — Postgres, Redis, RabbitMQ volumes."
        read -r -p "Type 'nuke' to confirm: " CONFIRM
        if [[ "$CONFIRM" != "nuke" ]]; then
            echo "Aborted. Nothing was removed."
            exit 1
        fi
        compose --profile full --profile observability down -v
        echo "Removed containers and volumes."
        ;;

    *)
        sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
        exit 1
        ;;
esac
