# Mobile Runbook — auth chain and app shell

Covers the Phase 1 surface: device-bound login, rotating refresh with reuse
detection, logout, and per-device revoke, plus running the Expo app against a
local stack. Verified end to end on 2026-08-02.

## 1. Bring up the backend

```bash
docker compose -f infra/docker-compose.yml up -d postgres redis auth-service gateway
docker compose -f infra/docker-compose.yml exec auth-service python manage.py migrate
```

Only these four services are needed for the auth flow — do not start the full
profile on a laptop (see the compose-profile note in the main `RUNBOOK.md`).

**Gotcha — stale pgbouncer pidfile.** If `auth-service` never becomes healthy,
check `docker logs suerp-pgbouncer` for:

```
FATAL pidfile '/tmp/pgbouncer.pid' exists, another instance running?
```

Fix with `docker compose -f infra/docker-compose.yml up -d --force-recreate pgbouncer`.
Do *not* `docker rm -f` the container on its own — that drops its compose
network alias and `auth-service` then fails with
`failed to resolve host 'pgbouncer'`.

**Gotcha — stale image.** The compose image is built, not mounted. After
changing `accounts/urls.py` or any view, rebuild or the gateway will return a
Django 404 for the new routes:

```bash
docker compose -f infra/docker-compose.yml up -d --build auth-service
```

## 2. Gateway routing

No gateway change was needed for Phase 1. `gateway/nginx.conf` already has a
prefix block:

```nginx
location /api/v1/auth/ {
    limit_req zone=api_limit burst=20 nodelay;
    set $up auth-service:8000;
    proxy_pass http://$up;
}
```

`/logout` and `/devices` fall under it. Confirm Nginx is resolving them rather
than 404ing at the edge:

```bash
curl -s -X POST http://localhost:8080/api/v1/auth/logout \
  -H 'Content-Type: application/json' -d '{"refresh":"garbage"}'
# {"success":true,"data":null,"message":"Logged out.","errors":null}

curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/api/v1/auth/devices
# 401  (auth required — NOT 404)
```

## 3. Create a test student

The seeded tenant is `iiitdmj` (plus the internal `platform`). Confirm what
your database actually holds before signing in — a wrong slug fails with
"Unknown or inactive institution", which reads like a broken app rather than a
typo:

```bash
docker compose -f infra/docker-compose.yml exec -T auth-service python manage.py shell -c "
from accounts.models import Institution
print([i.slug for i in Institution.objects.all()])
"
```

Seeded user passwords are not recorded, so make a throwaway:

```bash
docker compose -f infra/docker-compose.yml exec -T auth-service python manage.py shell -c "
from accounts.models import Institution, User
inst = Institution.objects.get(slug='iiitdmj')
u, _ = User.objects.get_or_create(
    user_code='MOB-TEST-001',
    defaults=dict(tenant=inst, email='mobile.test@iiitdmj.ac.in', role=User.Role.STUDENT),
)
u.set_password('s3cur3-passw0rd')
u.is_active = True
u.save()
"
```

## 4. Verified curl sequence

### Login, rotate, replay the rotated token

```bash
BASE=http://localhost:8080/api/v1/auth
TOKENS=$(curl -s -X POST $BASE/login -H 'Content-Type: application/json' \
  -d '{"institution_slug":"iiitdmj","email":"mobile.test@iiitdmj.ac.in","password":"s3cur3-passw0rd","device_id":"curl-device","platform":"android","model_name":"curl"}')
REFRESH=$(echo "$TOKENS" | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["refresh"])')
curl -s -X POST $BASE/refresh -H 'Content-Type: application/json' -d "{\"refresh\":\"$REFRESH\"}"
curl -s -X POST $BASE/refresh -H 'Content-Type: application/json' -d "{\"refresh\":\"$REFRESH\"}"
```

Actual output:

```
LOGIN:      True  Login successful.  access_len=327 refresh_len=328
REFRESH #1: True  Token refreshed.
REFRESH #2: {"success":false,"data":null,
             "message":"Refresh token was already used; device chain revoked.",
             "errors":null}   HTTP=401
```

The second refresh is the reuse case: presenting an already-rotated token
revokes the whole device chain rather than just rejecting the one token.

### Device list and revoke

```
DEVICES:                     ['curl-tablet', 'curl-phone', 'curl-device']
DELETE /devices/curl-tablet: {"success":true,...,"message":"Device signed out."}  HTTP=200
tablet refresh afterwards:   {"success":false,...,"message":"Refresh token is revoked or expired."}  HTTP=401
DELETE /devices/no-such-device: HTTP=404
```

Another user's `device_id` also returns 404, not 403 — the endpoint must not
leak which device ids exist.

### Logout, and web backward compatibility

```
POST /logout:                {"success":true,...,"message":"Logged out."}  HTTP=200
refresh after logout:        HTTP=401
web login (no device fields): True  Login successful.
web refresh (untracked token): HTTP=200
```

The last two matter: the web app posts login without device fields and refreshes
a token that has no `RefreshTokenRecord`. Both keep the original stateless path.

Clean up afterwards:

```bash
docker compose -f infra/docker-compose.yml exec -T auth-service python manage.py shell -c "
from accounts.models import Device, RefreshTokenRecord
d = Device.objects.filter(device_id__startswith='curl-')
RefreshTokenRecord.objects.filter(device__in=d).delete()
d.delete()
"
```

## 5. Run the app

### Over USB (recommended — no LAN IP needed)

```bash
adb devices                     # enable USB debugging on the phone first
adb reverse tcp:8081 tcp:8081   # Metro
adb reverse tcp:8080 tcp:8080   # gateway  ← easy to forget; without it every
                                #            API call fails though the app loads
cd mobile/su-erp-app
cp .env.example .env            # set EXPO_PUBLIC_API_BASE_URL=http://localhost:8080
npx expo start
```

With both ports reversed, the phone's `localhost` reaches your laptop, so
`http://localhost:8080` is correct and the LAN-IP problem disappears. Verify the
tunnel before blaming the app:

```bash
adb shell 'curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/api/v1/auth/devices'
# 401 = reachable (auth required).  502 = auth-service down.  000 = no reverse.
```

**Reversals are lost** whenever the adb daemon restarts or you run
`adb shell pm clear host.exp.exponent`. Re-run both `adb reverse` commands after
either.

### Over Wi-Fi

`EXPO_PUBLIC_API_BASE_URL` must be your machine's LAN IP (e.g.
`http://192.168.1.10:8080`). On a physical device `localhost` resolves to the
phone itself, not your laptop, and every request fails with a network error that
looks like the gateway being down.

`.env` is read only at Metro startup — restart `expo start` after editing it.

Log in with the institution slug, the test email, and the password above. You
should land on the student home screen showing your email and user code.

**Verified on device** (Motorola edge 50 fusion, Android 16, Expo Go SDK 57):
login registered a device row with a SecureStore-generated `device_id` and one
live refresh token, and `/api/v1/auth/me` populated the student screen.

To confirm revoke ends the session: with the app signed in, revoke the app's own
`device_id`, then restart the app to force `restore()`.

```bash
docker compose -f infra/docker-compose.yml exec -T auth-service python manage.py shell -c "
from accounts.models import Device
from accounts.token_service import revoke_device_chain
d = Device.objects.get(device_id='<the-app-device-id>')
print('revoked', revoke_device_chain(d))
"
adb shell am force-stop host.exp.exponent
adb shell am start -a android.intent.action.VIEW -d 'exp://localhost:8081' host.exp.exponent
```

Verified: the app lands on the login screen rather than a stale shell —
`restore()` refreshes against the revoked chain, gets a 401, and signs out.

**Gotcha — a stale session hides login failures.** If the app still holds a
refresh token from an earlier run, `restore()` signs you straight in and the
login form never submits, so a broken login looks like a working one. Confirm a
login actually reached the backend by checking for a `LoginAudit` row rather
than trusting the screen. `adb shell pm clear host.exp.exponent` wipes
SecureStore for a genuinely cold start (and drops the `adb reverse` tunnels —
re-add them).

## 6. Test suites

```bash
cd services/auth-service && ../../.venv/bin/python -m pytest accounts/ -q   # 110 passed
cd mobile/su-erp-app && npx tsc --noEmit && npx jest                        # 23 passed
```

**Gotcha — jest version pinning.** `mobile/su-erp-app/package.json` carries
`overrides` holding the jest packages at 30.4.1 and a dev dependency on
`@react-native/jest-preset`. Both are load-bearing: `jest-runtime@30.4.2` calls
a `jest-mock` API that has no published 30.4.2 counterpart, and `jest-expo`
declares the RN preset as an unbundled peer. Without them the suite fails to
start with `this._moduleMocker.clearMocksOnScope is not a function`.

**Gotcha — do not install reanimated / gesture-handler / worklets.**
`expo-router` lists `react-native-reanimated` and `react-native-gesture-handler`
as peers but marks both `optional: true`, and Phase 1 uses no animations.
Installing them pulls in `react-native-worklets`, which segfaults Expo Go on
launch — `Fatal signal 11 (SIGSEGV)` on the `mqt_v_js` thread, with
`libworklets.so` calling into Hermes' `memcpy`. The process dies before any JS
error can surface, so there is no redbox: the app just bounces back to the Expo
Go home screen. Only `react-native-safe-area-context` and
`react-native-screens` are genuinely required.

**Gotcha — stale docker-proxy holds the ports.** If `docker compose up` fails
with `ports are not available: ... address already in use` while `docker ps`
shows nothing running, orphaned root-owned `docker-proxy` processes are still
bound. `docker compose down` does not clear them:

```bash
sudo pkill -f docker-proxy      # or: sudo systemctl restart docker
```

**Gotcha — `create-expo-app` on npm 12.** The scaffolder cannot parse npm 12's
`npm pack --dry-run` output and exits with
`Could not parse JSON returned from "npm pack ..."` after creating nothing. The
project was scaffolded by extracting the template tarball directly:

```bash
npm pack expo-template-blank-typescript@latest --pack-destination .
tar -xzf expo-template-blank-typescript-*.tgz --strip-components=1
```

---

# Phase 2 — student surface

Home, fees, canteen, hostel, transport, grievance, notifications, profile, and
orders, over a query cache that survives a cold start. Verified end to end on
2026-08-03 on a Motorola edge 50 fusion (Android 16, Expo Go SDK 57).

## 1. Bring up the services this phase needs

```bash
docker compose -f infra/docker-compose.yml up -d postgres redis rabbitmq \
  auth-service hostel-service finance-service canteen-service \
  transport-service grievance-service notification-service gateway
```

This is the `default` profile set — do not start the observability profile
alongside it on a laptop.

A service that is down shows as `502` at the gateway and reaches the app as
"Could not load the menu". Probe before debugging the app:

```bash
for p in notify/inbox menu-items/ orders/ finance/invoices \
         hostel/allocations/mine transport/routes grievance; do
  printf '%s  /api/v1/%s\n' \
    "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/api/v1/$p)" "$p"
done
```

Every line should read `401` (up, auth required). `502` means that service is
not running; `404` usually means a stale image — rebuild with
`docker compose -f infra/docker-compose.yml up -d --build <service>`.

## 2. Seed demo data

Every screen renders empty on a fresh database, which makes the app impossible
to evaluate. The seed is idempotent:

```bash
scripts/seed_student_demo.sh            # defaults to MOB-TEST-001
```

It creates a canteen menu (one item sold out), invoices in both paid and
pending states — with real `Payment` and `Receipt` rows behind the paid ones,
so "View receipt" works — notifications, a hostel block with rooms and a
confirmed allocation, two bus routes with seats 1/2/7 already taken, and
grievance tickets.

## 3. Walk the student flow

Signed in as the test student, each of these was confirmed on device:

| Screen | Verified |
| --- | --- |
| Home | dues `₹51,500.00` with lakh grouping, room from `/allocations/mine`, unread badge |
| Fees | invoices list, Razorpay sheet opens, receipt renders in-app |
| Canteen | cart totals live, order places, active order shows its kitchen stage |
| Orders | in-progress split from history, spend counts collected orders only |
| Transport | routes, schedules, 32-seat grid with taken seats disabled, booking drops the free count |
| Grievance | ticket files and appears in the list |
| Notifications | inbox lists, tapping marks read optimistically |

## 4. Offline behaviour

**`adb reverse` tunnels over USB, so airplane mode alone does not isolate the
phone.** NetInfo reports offline and the banner appears, but requests still
reach the laptop over the cable and the app keeps refreshing. To test offline
for real, **unplug the phone** (or stop the reverse tunnels).

Observed with the cable disconnected:

| Check | Result |
| --- | --- |
| Offline banner | appears, reading "Offline — showing data from N min ago" |
| Cached screens | home, fees, canteen, alerts, help all still render |
| Fee payment | refuses with the offline message; never queues |
| Grievance | accepted, "Saved. It will be sent when you are back online" |
| Reconnect | queued grievances replay and appear without a manual refresh |

Payments and seat bookings deliberately do not queue: a fee that fires an hour
late, or a booking that claims a seat someone else already took, is worse than
one that fails in front of the student. Grievances do queue — hostel blocks are
where complaints get raised and where the signal dies.

## 5. Gotchas found in this phase

**Reanimated segfaults under Expo Go.** `react-native-reanimated` and
`react-native-worklets` are blocked at the Metro resolver in
`metro.config.js`. Expo Go ships its own `libworklets.so`; importing reanimated
initializes that native runtime against a mismatched JS side and kills the app
on launch (SIGSEGV on `mqt_v_js`). Both packages reappear in `node_modules` on
any `npm install` because expo-router lists them as optional peers — that is
expected and harmless while the resolver block stands. Motion uses RN core
`Animated`.

**MMKV needs a custom dev build.** `react-native-mmkv` v3+ is built on Nitro
modules, which Expo Go does not ship. Every read and write fails with "the
native NitroModules Turbo/Native-Module could not be found" while the app keeps
running, so persistence silently does nothing. The query cache uses
AsyncStorage instead.

**`LayoutAnimation` is a no-op** on the New Architecture and warns on every
launch. Animate layout changes with `Animated` values instead.

## 6. Phase 3 — field roles (warden, driver, canteen owner)

Three staff surfaces plus the three backend endpoints they depend on:
`VisitorLog` in hostel-service, driver trips/breadcrumbs in transport-service,
and `PATCH /grievance/<id>/status` in grievance-service.

### Test suites

```bash
cd services/hostel-service    && python -m pytest -q   # 98 passed, 4 skipped
cd ../transport-service       && python -m pytest -q   # 33 passed
cd ../grievance-service       && python -m pytest -q   # 24 passed
cd mobile/su-erp-app && npx jest && npx tsc --noEmit    # 107 passed / 19 suites, no type errors
```

Four hostel tests (`test_allocate`, `test_allocate_with_fee`,
`test_room_request_approval` ×2) were failing when this phase started — not
regressions, but time-bombed fixtures: they hard-coded `due_date:
"2026-08-01"`, which `validate_future_due_date` correctly rejects once that
date passes. Fixed in `fix(hostel): anchor test due_dates to today`, which
replaces every literal with `_future_due_date()` / `_past_due_date()` helpers
computed from `timezone.now()`. The suite can no longer expire.

### Bringing the stack up

Transport-service is behind the `full` profile. New migrations are baked into
the images, so the three changed services must be **rebuilt**, not just
restarted — `manage.py migrate` against a stale image reports "No migrations to
apply" while the table is genuinely missing.

```bash
docker compose -f infra/docker-compose.yml build hostel-service grievance-service
docker compose -f infra/docker-compose.yml --profile full build transport-service
docker compose -f infra/docker-compose.yml --profile full up -d \
  hostel-service grievance-service transport-service
```

### Verified against the live stack (gateway :8080)

Token minted through a real login — see `services/hostel-service/.claude/skills/verify`.

| Flow | Check | Result |
| --- | --- | --- |
| Warden | `POST /hostel/visitors` | 201, `checked_out_at: null` |
| Warden | `POST /hostel/visitors/<id>/checkout` | 200, exit time stamped |
| Warden | checkout twice | 400 "already checked out" |
| Warden | `GET /hostel/visitors` after checkout | empty (still-inside filter) |
| Warden | `GET /hostel/visitors?all=true` | 1 row, full history |
| Warden | grievance `open → in_progress → resolved` | 200 each |
| Warden | `resolved → open` | 400 "Illegal transition" |
| Warden | unknown status `banana` | 400 |
| Driver | `POST /schedules/<id>/trips` | 201, trip active |
| Driver | start a second trip on same schedule | 400 |
| Driver | `GET /routes/<id>/live` before any breadcrumb | 404 |
| Driver | breadcrumb batch | 201, points stored |
| Driver | `GET /routes/<id>/live` after batch | newest point returned |
| Driver | `POST /trips/<id>/end` | 200, `ended_at` set |
| Driver | end twice | 400 |
| Driver | live position after end | 404 (dot dropped, not left to expire) |
| Owner | `PATCH /menu-items/<id>/` availability + price | 200, price returns as string `"75.50"` |
| Owner | order `placed → preparing → ready → completed` | 200 each |
| Owner | `completed → preparing` | 400 "Illegal transition" |
| Owner | student attempting a status change | 403 |

### Breadcrumb replay across a signal gap

The check that matters for the offline queue: a replayed batch must not
duplicate the trail, and the trail must keep its real shape rather than
collapsing into the reconnect instant.

Batch 1 sent `08:01:00` and `08:01:15`. Batch 2 replayed `08:01:00` and added
`08:02:00` and `08:03:00` (spanning a two-minute tunnel). Five points
submitted, **four rows stored** — the replayed point deduplicated against the
`(trip, recorded_at)` uniqueness constraint:

```
2026-08-04T08:01:00+00:00  12.971599 77.594566
2026-08-04T08:01:15+00:00  12.972000 77.595000
2026-08-04T08:02:00+00:00  12.973000 77.596000
2026-08-04T08:03:00+00:00  12.974000 77.597000
```

Timestamps are device-stamped, so the gap survives the replay intact.

### Deviation from the plan: the warden roster endpoint

The plan specified reusing `fetchMyAllocations` (`GET /hostel/allocations/mine`)
for the block roster, on the assumption that a warden's token returns the whole
block. It does not — that view is `role_required("student")` and answers "where
do I live". Verified against the running stack:

```
GET /hostel/allocations/mine          (staff token) -> 403
GET /hostel/allocations?status=confirmed (staff token) -> 200
```

The app therefore uses `fetchBlockRoster()` against the tenant-scoped
`AllocationListView`, which its own docstring calls "what a warden needs".

### On-device walkthrough

Verified on a **Motorola Edge 50 Fusion** (Android, Expo Go, `adb reverse`),
signed in as real `warden` / `driver` / `canteen_owner` users rather than an
admin token — so this is the first run that exercised the actual role gating.

Staff accounts in the `iiitdmj` tenant (`s3cur3-passw0rd`):
`warden.test@iiitdmj.ac.in` (WRD-001), `driver.test@iiitdmj.ac.in` (DRV-001),
`canteen.test@iiitdmj.ac.in` (CAN-001).

| Role | On-device check | Result |
| --- | --- | --- |
| Warden | Block roster | Room-grouped SectionList, "1 resident across 1 room", header `NEHRU BLOCK - A-101` |
| Warden | Log visitor | Form clears, list refreshes, row shows "In since 3:12 pm" |
| Warden | Check out | Row leaves "Currently inside"; server shows `logged_by: WRD-001` with both timestamps |
| Driver | Start trip | Full-screen running state; GPS permission already granted, `watchPosition` engaged |
| Driver | Breadcrumbs | **Real fix recorded: `23.182596, 80.024324`** (Jabalpur) with a device-stamped `recorded_at` |
| Driver | Live position | Returns the newest point immediately after ingest |
| Driver | Riders | "4 booked seats", seat-ordered 1/2/3/7 — cancelled bookings correctly filtered out |
| Driver | End trip | `ended_at` stamped; `/live` drops to 404 (dot deleted, not left to expire) |
| Owner | Order board | Lanes render; `₹30.00` via `Money`, "Hand over" label from `NEXT_LABEL` |
| Owner | Advance order | Order reaches `completed`, leaves the board; `total` still arrives as a **str** |
| Owner | Menu availability | Switch persists (`available=false`), row shows "Hidden from students right now." |
| Owner | Menu price | Commits on blur as `'38.50'` — string end to end, never a number |

The 60-second live-position TTL is real: reading `/live` a couple of minutes
after the last breadcrumb correctly 404s rather than showing a stale dot.

### Bug found on-device: unreachable ≠ offline

The queue never fired at the gate, and unit tests could not have caught it
because they mock `request`.

`NetInfo` reports online whenever the **radio** is up. A phone with full bars
but no route to the gateway therefore took the online path — and `client.ts`
had no timeout, so `fetch` hung on a dead socket forever. The mutation never
resolved, never rejected, and never reached the offline queue. Observed
directly: form stayed populated, no snackbar, nothing sent, and the warden
would reasonably believe the visitor was logged.

Fixed in `fix(mobile): queue mutations when the server is unreachable`:

- `client.ts` — 12s `AbortController` deadline; unreachable surfaces as
  `NetworkError`, distinct from an `ApiError` the server actually sent.
- Queueable mutations treat `NetworkError` as offline and enqueue. HTTP errors
  still throw, so a request the server *rejected* is never replayed.
- `connectivity.ts` — drain on the first success after an unreachable failure.
  NetInfo never fires in this case, so the queue would otherwise sit until an
  unrelated real network drop.

Re-verified on the device, with isolation proven before each step
(`adb shell curl ... http://localhost:8080` returning `HTTP:000`):

```
tunnel down, submit "Replay-Proof"  -> held on device; server still shows only "Asha"
adb reverse tcp:8080 tcp:8080       -> device->gateway HTTP:401 (reachable)
pull-to-refresh                     -> server: Replay-Proof | by: WRD-001
```

**Testing offline over USB is order-sensitive.** Removing the `adb reverse`
tunnel does not kill an already-open socket, and taps race the teardown — an
earlier attempt "queued" an entry that had in fact already reached the server.
Always confirm isolation with `adb shell curl` *before* interacting, and again
at the moment of submit.

### Known gap (not Phase 3 scope)

The three staff shells have **no sign-out path** — only the student shell has a
Profile tab. Switching roles on a device currently needs
`adb shell pm clear host.exp.exponent`. Worth a shared header action in a
later phase.

---

# Phase 4 — hardware features

Eight capabilities the web app cannot have: QR e-passes with offline
verification, geofenced attendance, the live bus map, camera-first grievances
with auto-purging media, canteen pickup tokens, push notifications, the
offline document vault, and home-screen widgets.

## What shipped, and what did not

| Feature | Backend | App | Status |
| --- | --- | --- | --- |
| QR bus pass + scan | transport-service | student `pass`, driver `scan` | shipped |
| Geofenced attendance | attendance-service | student `attendance` | shipped |
| Faculty session console | attendance-service | **web** `/faculty` | shipped |
| Camera grievance + purge | grievance-service | student `grievance` | shipped |
| Canteen pickup token | canteen-service | student `pickup`, owner `scan` | shipped |
| Push notifications | notification-service | `lib/push/register.ts` | shipped, off by default |
| Live bus map | (Phase 3 endpoint) | student `transport` | shipped |
| Document vault | (existing receipt PDFs) | student `vault` | shipped |
| Home-screen widgets | — | — | **deferred** |

**Widgets are deferred.** They need iOS/Android native targets and therefore a
custom dev build; this project runs on Expo Go and has no `eas.json`. The plan
anticipated this (Task 10 Step 4) and noted widgets have no backend dependency,
so deferring them blocks nothing.

## Faculty attendance — who opens a session

Geofenced attendance needs someone to open the session and project the
rotating code. `Role.FACULTY` existed in auth-service but had no console for
it, so this phase added one to the **web** dashboard (`/faculty`), not the
mobile app:

- open a session pinned to the room's coordinates (or the browser's location)
- the 6-digit code at projector size, polled every 5s, rotating every 15s
- the live roster of who has marked, polled every 10s
- close the session

Two endpoints were added for it: `GET /api/v1/attendance/sessions` (the
caller's own sessions) and `GET /api/v1/attendance/sessions/<id>/marks` (the
roster, faculty/admin only).

The pre-existing manual roll on that page still calls
`/api/v1/attendance/records`, which **does not exist** — the route is
`/api/v1/attendance/`. That 404 predates this phase and was left alone.

## Test suites

```bash
PY=.venv/bin/python
for s in shared/libs/suerp_common services/transport-service \
         services/attendance-service services/grievance-service \
         services/canteen-service services/notification-service; do
  (cd "$s" && ../../../$PY -m pytest -q)   # use an absolute path; depths differ
done
```

Observed, all green:

```
shared/libs/suerp_common        27 passed
services/transport-service      41 passed   (8 new)
services/attendance-service     15 passed   (13 new)
services/grievance-service      33 passed   (9 new)
services/canteen-service        20 passed   (7 new)
services/notification-service   19 passed   (10 new)
frontend/su-erp-web             67 passed   (4 new)
mobile/su-erp-app              114 passed   (5 new), tsc clean
```

Every other backend service was re-run unchanged and still passes (hostel's 4
skips are the pre-existing Postgres-only concurrency tests).

## NOT yet verified on a device

**Everything below is unverified on real hardware.** The suites above prove
the logic; they do not prove the app runs, because a passing bundle has been a
launch-crashing state in this repo before. A physical device is required — an
emulator cannot exercise camera, GPS, or push honestly.

- **QR pass:** open the pass screen, confirm the code re-renders within 30s,
  scan from the driver device, confirm acceptance, then re-scan the same
  screenshot and confirm a 409.
- **Attendance:** open a session from the web `/faculty` console, mark from
  inside the room, then walk outside the radius and confirm refusal. Also
  confirm the roster row appears on the console within ~10s.
- **Live bus:** start a driver trip, confirm the student map marker moves.
- **Camera grievance:** attach a photo, resolve the ticket, backdate
  `expires_at`, run `purge_expired_media_task`, confirm the row reads
  "1 attachment, purged <date>" with the file gone.
- **Pickup token:** advance an order to ready, scan from the owner device,
  confirm completion.
- **Push:** requires `PUSH_ENABLED=true` **and a custom dev build** — Expo Go
  dropped Android remote push in SDK 53, so this cannot be tested in Expo Go
  at all. `expo-notifications` is imported lazily for exactly this reason.
- **Vault:** save a receipt, enable airplane mode, confirm it still lists,
  opens, and shares.

## Gotchas found in this phase

**`IntegrityError` inside an outer transaction poisons it.** The duplicate-mark
path in `MarkAttendanceView` returned 409 by catching `IntegrityError`, but the
serializer query in the response then failed with
`TransactionManagementError: An error occurred in the current transaction`.
Fixed by wrapping the insert in its own nested `transaction.atomic()`, the same
shape `ScanView` uses in transport-service.

**Test uploads were landing in the repo.** grievance-service had no
`MEDIA_ROOT`, so `FileField` wrote `grievance-media/` into the service root and
git picked it up. Set `MEDIA_ROOT` to `BASE_DIR/media` and ignored
`services/*/media/`.

**`expo-file-system` v57 has two APIs.** The root export is the new
`File`/`Directory` classes; `deleteAsync` lives only at
`expo-file-system/legacy`. The vault uses the modern `File`/`Paths` API
(matching `useReceipt.ts`); `mediaQueue.ts` uses the legacy `deleteAsync` for
its one delete-by-uri call.

**Importing `expo-notifications` has side effects.** It runs device-token
auto-registration at module load and warns that Expo Go cannot do remote push.
Both the root layout and `lib/push/register.ts` import it lazily so app launch
and the test suite stay clean.

**The student tab bar is full.** Material caps a navigation bar at 5, and the
existing layout documents that. `pass`, `attendance`, `pickup`, and `vault` are
registered with `href: null` and reached from the home screen, like `hostel`
and `transport` already were.

## Known gaps after Phase 4

Recorded honestly rather than left implied:

- **Symmetric scan key.** `GET /api/v1/transport/scan-key` hands the shared
  HS256 secret to scanner devices, so a compromised driver phone can mint
  valid passes. That is the cost of verifying a pass at a gate with no
  network. Mitigations in place: role-gated to driver/warden/admin, stored in
  SecureStore, and every scan logged with its nonce so replay is detectable.
  Moving to asymmetric signing (server holds the private key, scanners hold
  only the public key) removes this entirely and is the right next security
  task; it needs a key-distribution story the platform does not yet have.
- **BLE proximity attendance.** Deferred — it needs a room beacon, since
  faculty has no app. Geofence plus rolling code is the shipped defense.
- **Queued attendance marks expire.** A mark queued longer than ~30 seconds
  carries a stale code and is refused on replay. Deliberate: accepting old
  codes would reopen exactly the proxy hole the code exists to close.
- **Widgets require a dev build.** Not testable in Expo Go, and not shipped.
- **Push is best-effort.** No delivery receipts beyond stale-token pruning and
  no retry — the in-app inbox remains the source of truth. It also cannot run
  in Expo Go at all.
- **Nothing in this phase is device-verified.** See the list above.
- **The faculty page's manual roll form posts to a route that does not
  exist** (`/api/v1/attendance/records`; the real one is
  `/api/v1/attendance/`). Predates this phase.
