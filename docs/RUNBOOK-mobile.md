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
