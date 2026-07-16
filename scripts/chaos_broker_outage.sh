#!/usr/bin/env bash
# Chaos proof: the transactional outbox survives a broker outage.
#
# Kills RabbitMQ in the middle of a live hostel saga and shows that:
#
#   1. the API keeps accepting writes while the broker is DOWN — the state
#      change and the event commit together to Postgres, so a dead broker
#      cannot fail or roll back a user's request;
#   2. events accumulate as unpublished outbox rows (published_at IS NULL)
#      instead of being silently dropped, which is what a naive
#      "publish inside the request" design would do;
#   3. when RabbitMQ comes back, celery-beat's drain task publishes the
#      backlog and the saga completes on its own — no manual replay.
#
# This is the dual-write problem: without an outbox, a broker that dies between
# "row committed" and "event published" loses the event forever and the saga
# wedges. Run this against the compose stack:
#
#     ./scripts/chaos_broker_outage.sh
#
# Exits non-zero if the system fails to recover.

set -euo pipefail

API="${API:-http://localhost:8080}"
SLUG="${SLUG:-nitj}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@nitj.in}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-12345678}"
COMPOSE="docker compose -f infra/docker-compose.yml"

bold() { printf '\033[1m%b\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }
info() { printf '  · %s\n' "$*"; }

unpublished() {
  docker exec suerp-postgres psql -U suerp -d hostel -tAc \
    "SELECT count(*) FROM suerp_common_outboxevent WHERE published_at IS NULL;" 2>/dev/null | tr -d '[:space:]'
}

alloc_status() {
  docker exec suerp-postgres psql -U suerp -d hostel -tAc \
    "SELECT status FROM hostel_allocation WHERE id='$1';" 2>/dev/null | tr -d '[:space:]'
}

cleanup() {
  if ! docker ps --format '{{.Names}}' | grep -q '^suerp-rabbitmq$'; then
    bold "\nrestoring RabbitMQ (script interrupted)"
    $COMPOSE start rabbitmq >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

bold "== chaos: broker outage mid-saga =="

# --- setup -----------------------------------------------------------------
TOKEN=$(curl -s -X POST "$API/api/v1/auth/login" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASSWORD\",\"institution_slug\":\"$SLUG\"}" \
  | jq -r '.data.access')
[ -n "$TOKEN" ] && [ "$TOKEN" != "null" ] || { bad "admin login failed"; exit 1; }
ok "authenticated as $ADMIN_EMAIL"

ROOM=$(curl -s "$API/api/v1/hostel/rooms/available" -H "Authorization: Bearer $TOKEN" \
  | jq -r '(.data.results // .data // [])[0].id')
FEE=$(curl -s "$API/api/v1/finance/fee-structures" -H "Authorization: Bearer $TOKEN" \
  | jq -r '(.data.results // .data // [])[0].id')
[ "$ROOM" != "null" ] && [ -n "$ROOM" ] || { bad "no available room to allocate"; exit 1; }
[ "$FEE" != "null" ] && [ -n "$FEE" ]  || { bad "no fee structure configured"; exit 1; }
ok "room $ROOM / fee $FEE"

# hostel-service validates student_user_code against auth-service, and rejects a
# student who already holds an active allocation — so pick a real, unallocated one.
ACTIVE=$(docker exec suerp-postgres psql -U suerp -d hostel -tAc \
  "SELECT student_user_code FROM hostel_allocation WHERE status IN ('pending','confirmed');" 2>/dev/null \
  | tr -d ' ' | grep -v '^$' | sort -u | tr '\n' '|' | sed 's/|$//')
STUDENT=$(curl -s "$API/api/v1/auth/users?page_size=100&is_active=true" -H "Authorization: Bearer $TOKEN" \
  | jq -r '(.data.results // [])[] | select(.role=="student") | .user_code' \
  | grep -vE "^(${ACTIVE:-ZZZ_NONE})$" | head -1)
[ -n "$STUDENT" ] || { bad "no student without an active allocation — free one up or seed another"; exit 1; }
ok "student $STUDENT (no active allocation)"

BASELINE=$(unpublished)
info "outbox backlog before: $BASELINE unpublished"

# --- 1. kill the broker ----------------------------------------------------
bold "\n[1] killing RabbitMQ mid-flight"
$COMPOSE stop rabbitmq >/dev/null 2>&1
docker ps --format '{{.Names}}' | grep -q '^suerp-rabbitmq$' \
  && { bad "RabbitMQ still running"; exit 1; }
ok "RabbitMQ is DOWN"

# --- 2. write while the broker is dead -------------------------------------
bold "\n[2] allocating a seat with NO broker (the write must still succeed)"
DUE=$(date -d '+14 days' +%Y-%m-%d 2>/dev/null || date -v+14d +%Y-%m-%d)
RESP=$(curl -s -X POST "$API/api/v1/hostel/allocate" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"room_id\":\"$ROOM\",\"student_user_code\":\"$STUDENT\",\"fee_structure_id\":\"$FEE\",\"due_date\":\"$DUE\"}")

ALLOC=$(echo "$RESP" | jq -r '.data.id // empty')
if [ -z "$ALLOC" ]; then
  bad "allocation REJECTED while broker was down — the outbox is not decoupling the write"
  echo "$RESP" | jq -c '{success,message,errors}'
  exit 1
fi
ok "HTTP 201 — allocation $ALLOC created with the broker DOWN"
ok "status: $(alloc_status "$ALLOC") (committed to Postgres)"

sleep 6  # give celery-beat (5s cadence) a chance to try, and fail, to publish

DURING=$(unpublished)
if [ "$DURING" -le "$BASELINE" ]; then
  bad "expected the event to be queued in the outbox; backlog did not grow ($BASELINE -> $DURING)"
  exit 1
fi
ok "event is SAFE in the outbox, unpublished: backlog $BASELINE -> $DURING"
info "a naive publish-in-request design would have lost this event"

# --- 3. recover ------------------------------------------------------------
bold "\n[3] bringing RabbitMQ back"
$COMPOSE start rabbitmq >/dev/null 2>&1
info "waiting for the broker to pass its healthcheck..."
for _ in $(seq 1 60); do
  [ "$($COMPOSE ps rabbitmq --format '{{.Status}}' 2>/dev/null | grep -c healthy)" -gt 0 ] && break
  sleep 2
done
ok "RabbitMQ is UP and healthy"

# --- 4. self-healing -------------------------------------------------------
bold "\n[4] waiting for the outbox to drain by itself (beat runs every 5s)"
DRAINED=0
for i in $(seq 1 24); do
  NOW=$(unpublished)
  printf '\r  · backlog: %s unpublished (t=%ss)   ' "$NOW" "$((i * 5))"
  if [ "$NOW" -le "$BASELINE" ]; then DRAINED=1; break; fi
  sleep 5
done
echo ""

if [ "$DRAINED" -ne 1 ]; then
  bad "outbox did not drain — backlog stuck at $(unpublished)"
  exit 1
fi
ok "backlog drained back to $BASELINE — no manual replay, no lost events"

FINAL=$(alloc_status "$ALLOC")
ok "allocation $ALLOC final status: $FINAL"

# --- 5. the saga actually completed across the bus --------------------------
# Draining the outbox only proves the event left this service. The real question
# is whether the *downstream* saga step ran: finance consumes
# hostel.allocation.requested and raises the invoice.
bold "\n[5] confirming the downstream saga step ran (finance raised the invoice)"
INVOICE=""
for _ in $(seq 1 12); do
  INVOICE=$(docker exec suerp-postgres psql -U suerp -d finance -tAc \
    "SELECT amount FROM billing_invoice WHERE student_user_code='$STUDENT' ORDER BY created_at DESC LIMIT 1;" 2>/dev/null | tr -d '[:space:]')
  [ -n "$INVOICE" ] && break
  sleep 5
done

if [ -z "$INVOICE" ]; then
  bad "no invoice raised for $STUDENT — the event drained but the saga did not complete"
  exit 1
fi
ok "finance consumed the recovered event and raised an invoice for $INVOICE"

bold "\n== result =="
echo "  The broker died mid-saga. The API kept serving writes, the event waited"
echo "  in the outbox instead of vanishing, and the backlog published itself once"
echo "  RabbitMQ returned — then finance consumed it and raised the invoice."
echo "  No data lost, no operator intervention, saga completed end to end."
