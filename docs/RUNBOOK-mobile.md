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

The seeded tenants are `pdpmiiitdmj`, `nitj`, `iitrpr` (plus the internal
`platform`). Seeded user passwords are not recorded, so make a throwaway:

```bash
docker compose -f infra/docker-compose.yml exec -T auth-service python manage.py shell -c "
from accounts.models import Institution, User
inst = Institution.objects.get(slug='pdpmiiitdmj')
u, _ = User.objects.get_or_create(
    user_code='MOB-TEST-001',
    defaults=dict(tenant=inst, email='mobile.test@pdpmiiitdmj.ac.in', role=User.Role.STUDENT),
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
  -d '{"institution_slug":"pdpmiiitdmj","email":"mobile.test@pdpmiiitdmj.ac.in","password":"s3cur3-passw0rd","device_id":"curl-device","platform":"android","model_name":"curl"}')
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

```bash
cd mobile/su-erp-app
cp .env.example .env      # then edit EXPO_PUBLIC_API_BASE_URL
npx expo start
```

**Gotcha — LAN IP.** `EXPO_PUBLIC_API_BASE_URL` must be your machine's LAN IP
(e.g. `http://192.168.1.10:8080`). On a physical device `localhost` resolves to
the phone itself, not your laptop, and every request fails with a network error
that looks like the gateway being down.

Log in with the institution slug (`pdpmiiitdmj`), the test email, and the
password above. You should land on the student home screen showing your email
and user code.

To confirm revoke ends the session: with the app signed in, list devices, revoke
the app's own `device_id`, then restart the app to force `restore()`. The app
lands on the login screen rather than a stale shell — `restore()` refreshes
against a revoked chain, gets a 401, and signs out.

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

**Gotcha — `create-expo-app` on npm 12.** The scaffolder cannot parse npm 12's
`npm pack --dry-run` output and exits with
`Could not parse JSON returned from "npm pack ..."` after creating nothing. The
project was scaffolded by extracting the template tarball directly:

```bash
npm pack expo-template-blank-typescript@latest --pack-destination .
tar -xzf expo-template-blank-typescript-*.tgz --strip-components=1
```
