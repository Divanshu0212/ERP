# Mobile Phase 4 — Hardware-Only Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the eight capabilities the web app cannot have because it has no camera, GPS, secure enclave, or home screen: QR e-passes with offline verification, geofenced attendance, the live bus map, camera-first grievances with auto-purging media, canteen pickup tokens, home-screen widgets, and the offline document vault — plus push notifications, which make several of them useful.

**Architecture:** Each feature pairs a backend capability with a device capability. A shared HS256 signing scheme (reusing the existing `JWT_SIGNING_KEY` infrastructure) underpins both QR features, so passes verify at a gate with no network. Attendance fills the `attendance-service` stub entirely. Media retention is enforced by a celery-beat sweep alongside the existing outbox drain, not by request-time deletion.

**Tech Stack:** Django 5 + DRF + Celery beat (backend); `expo-camera`, `expo-location`, `expo-file-system`, `expo-sharing`, `react-native-qrcode-svg`, `expo-notifications`, `expo-apple-targets`/Android widget provider (app).

## Global Constraints

- Prerequisites: **Phases 1–3 are merged.**
- Spec: `docs/superpowers/specs/2026-08-02-mobile-app-design.md` §6, §7. Branch: `feat/mobile-app`.
- **Signed payloads use HS256 with the service's existing `JWT_SIGNING_KEY`** (`env("JWT_SIGNING_KEY", default="dev-insecure-change-me")`, already read by every service's settings). Pass tokens are *not* JWTs for authentication — they are short-lived signed capability tokens with their own claim set. Never accept one in an `Authorization` header.
- **Grievance media retention:** blobs are deleted **7 days after the ticket reaches `resolved`**. `Ticket.Status` has no `closed` value. Metadata (`media_count`, `sha256[]`, `captured_at`, `purged_at`) is retained indefinitely and shown in both the student's and the warden's log.
- Backend services here are tenant-scoped via `TenantModel`. Every new endpoint gets a cross-tenant isolation test.
- BLE proximity attendance is **out of scope** — it needs a room beacon, since faculty has no app. v1 is geofence plus rolling code (spec §6.2).
- Media uploads go through the offline media queue from Phase 1 (`src/lib/offline/`), not a fresh implementation.
- Commit as `Divanshu0212 <divanshubhargava026@gmail.com>`, no co-author trailer. Commit after every task.

---

## File Structure

**Backend**

| File | Responsibility |
| --- | --- |
| `shared/libs/suerp_common/suerp_common/signed_token.py` (create) | sign/verify short-lived capability tokens; used by transport and canteen |
| `services/transport-service/transport/pass_tokens.py` (create) | pass-specific claims over the shared signer |
| `services/transport-service/transport/views.py` (modify) | pass QR mint, scan-verify, `ScanLog` |
| `services/attendance-service/attendance/` (build out) | `Session`, `AttendanceMark`, geofence + rolling code |
| `services/grievance-service/grievance/models.py` (modify) | `TicketMedia` with `expires_at` |
| `services/grievance-service/grievance/tasks.py` (modify) | `purge_expired_media_task` on celery-beat |
| `services/canteen-service/canteen/views.py` (modify) | pickup-token mint and scan-to-complete |
| `services/notification-service/notify/push.py` (create) | push channel interface + Expo implementation |

**App**

| File | Responsibility |
| --- | --- |
| `src/lib/device/camera.ts`, `qr.ts`, `geofence.ts` | hardware behind interfaces |
| `src/features/pass/`, `attendance/`, `bustrack/`, `vault/` | per-feature hooks + screens |
| `src/lib/push/register.ts` | Expo push token registration |
| `widgets/` | iOS Live Activity + Android widget provider |

---

## Task 1: Shared signed-token helper

**Files:**
- Create: `shared/libs/suerp_common/suerp_common/signed_token.py`
- Create: `shared/libs/suerp_common/tests/test_signed_token.py`

**Interfaces:**
- Produces:
  - `sign(payload: dict, ttl_seconds: int) -> str`
  - `verify(token: str, expected_kind: str) -> dict` — raises `SignedTokenError` on bad signature, wrong kind, or expiry
  - `class SignedTokenError(Exception)`
  - Every payload carries `kind`, `tenant_id`, `iat`, `exp`, `nonce`.

- [ ] **Step 1: Write the failing tests**

Create `shared/libs/suerp_common/tests/test_signed_token.py`:

```python
"""Short-lived signed capability tokens (QR passes, pickup tokens).

These are NOT authentication tokens. They assert one narrow capability for
a few seconds and are verified offline by a scanner device that may have no
network at all.
"""

import time
import uuid

import pytest
from suerp_common.signed_token import SignedTokenError, sign, verify

TENANT = str(uuid.uuid4())


def test_a_signed_token_round_trips():
    token = sign({"kind": "bus_pass", "tenant_id": TENANT, "pass_id": "p1"}, ttl_seconds=30)

    claims = verify(token, expected_kind="bus_pass")

    assert claims["pass_id"] == "p1"
    assert claims["tenant_id"] == TENANT


def test_every_token_gets_a_unique_nonce():
    payload = {"kind": "bus_pass", "tenant_id": TENANT, "pass_id": "p1"}

    first = verify(sign(payload, ttl_seconds=30), expected_kind="bus_pass")
    second = verify(sign(payload, ttl_seconds=30), expected_kind="bus_pass")

    assert first["nonce"] != second["nonce"]


def test_a_tampered_token_is_rejected():
    token = sign({"kind": "bus_pass", "tenant_id": TENANT, "pass_id": "p1"}, ttl_seconds=30)
    tampered = token[:-4] + "AAAA"

    with pytest.raises(SignedTokenError):
        verify(tampered, expected_kind="bus_pass")


def test_a_token_of_the_wrong_kind_is_rejected():
    """A pickup token must never open a bus gate."""
    token = sign({"kind": "pickup", "tenant_id": TENANT, "order_id": "o1"}, ttl_seconds=30)

    with pytest.raises(SignedTokenError):
        verify(token, expected_kind="bus_pass")


def test_an_expired_token_is_rejected():
    token = sign({"kind": "bus_pass", "tenant_id": TENANT, "pass_id": "p1"}, ttl_seconds=1)
    time.sleep(2)

    with pytest.raises(SignedTokenError):
        verify(token, expected_kind="bus_pass")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd shared/libs/suerp_common && python -m pytest tests/test_signed_token.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'suerp_common.signed_token'`

- [ ] **Step 3: Write the module**

Create `shared/libs/suerp_common/suerp_common/signed_token.py`:

```python
"""Short-lived signed capability tokens.

A QR code shown at a gate cannot rely on the network — the scanner is on a
bus or standing at a hostel door. So the capability travels inside the code
itself, signed with the platform's shared HS256 key, and the scanner
verifies it locally.

These are deliberately NOT JWTs used for authentication: they carry a
``kind`` that scopes them to exactly one purpose, they live for seconds
rather than minutes, and they must never be accepted in an Authorization
header. ``JWTAuthentication`` will reject them anyway (no ``sub``/``role``
claims), but the ``kind`` check is the explicit guard.
"""

import secrets
import time

import jwt
from django.conf import settings


class SignedTokenError(Exception):
    """The token is malformed, tampered with, expired, or the wrong kind."""


def sign(payload: dict, ttl_seconds: int) -> str:
    """Sign a capability payload. ``kind`` and ``tenant_id`` are required."""
    if "kind" not in payload or "tenant_id" not in payload:
        raise ValueError("Signed tokens require 'kind' and 'tenant_id'.")

    now = int(time.time())
    claims = {
        **payload,
        "iat": now,
        "exp": now + ttl_seconds,
        # A fresh nonce per mint is what makes a screenshot useless: the
        # scanner records nonces it has seen and refuses a repeat.
        "nonce": secrets.token_urlsafe(12),
    }
    return jwt.encode(claims, settings.JWT_SIGNING_KEY, algorithm="HS256")


def verify(token: str, expected_kind: str) -> dict:
    """Verify signature, expiry, and kind. Returns the claims."""
    try:
        claims = jwt.decode(token, settings.JWT_SIGNING_KEY, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise SignedTokenError(str(exc)) from exc

    if claims.get("kind") != expected_kind:
        raise SignedTokenError(
            f"Token is for '{claims.get('kind')}', not '{expected_kind}'."
        )

    return claims
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd shared/libs/suerp_common && python -m pytest tests/test_signed_token.py -v`
Expected: all 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add shared/libs/suerp_common/
git commit -m "feat(common): add short-lived signed capability tokens"
```

---

## Task 2: QR bus pass — mint, scan, and ScanLog

**Files:**
- Modify: `services/transport-service/transport/models.py`
- Modify: `services/transport-service/transport/views.py`, `urls.py`, `serializers.py`
- Create: `services/transport-service/transport/tests/test_pass_qr.py`

**Interfaces:**
- Consumes: `sign`, `verify`, `SignedTokenError` (Task 1); `Pass` model (existing).
- Produces:
  - `ScanLog` model: `id`, `pass_id`, `scanned_by`, `nonce (unique)`, `scanned_at`, `accepted`
  - `GET /api/v1/transport/passes/mine/qr` — returns `{token, expires_in}` (student)
  - `POST /api/v1/transport/scans` — body `{token}`, driver/warden only, records the scan
  - `GET /api/v1/transport/scan-key` — returns the verification material the scanner caches at login

**Security note:** `/scan-key` returns the shared HS256 secret to scanner devices, which means a compromised driver phone can mint valid passes. That is the cost of offline verification with a symmetric key. Mitigations in scope: the endpoint is role-gated to driver/warden/admin, the key is stored in SecureStore, and every scan is logged with its nonce so replay is detectable. **Flagged for the plan owner:** moving to an asymmetric scheme (server signs with a private key, scanners hold only the public key) removes this exposure entirely and is the right end state — it is deferred here only because it requires a key-distribution story the platform does not yet have.

- [ ] **Step 1: Write the failing tests**

Create `services/transport-service/transport/tests/test_pass_qr.py`:

```python
"""QR bus passes: rolling mint, offline-verifiable, replay-resistant."""

import uuid

import pytest
from suerp_common.signed_token import sign
from transport.models import Pass, Route, ScanLog

pytestmark = pytest.mark.django_db

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


def _client(tenant_id, role="student", sub="STU-001"):
    from tests.helpers import auth_client  # noqa: PLC0415

    return auth_client(tenant_id=tenant_id, role=role, sub=sub)


def _pass(tenant_id, student="STU-001", active=True):
    route = Route.objects.create(
        tenant_id=tenant_id, name="North", start_point="Gate", end_point="Campus"
    )
    return Pass.objects.create(
        tenant_id=tenant_id, student_user_code=student, route=route, active=active
    )


def test_student_mints_a_qr_for_their_active_pass():
    _pass(TENANT_A)
    client = _client(TENANT_A)

    response = client.get("/api/v1/transport/passes/mine/qr")

    assert response.status_code == 200
    assert response.json()["data"]["token"]
    assert response.json()["data"]["expires_in"] == 30


def test_a_student_without_an_active_pass_gets_404():
    _pass(TENANT_A, active=False)
    client = _client(TENANT_A)

    response = client.get("/api/v1/transport/passes/mine/qr")

    assert response.status_code == 404


def test_driver_scan_accepts_a_fresh_token():
    bus_pass = _pass(TENANT_A)
    token = _client(TENANT_A).get("/api/v1/transport/passes/mine/qr").json()["data"]["token"]

    driver = _client(TENANT_A, role="driver", sub="DRV-001")
    response = driver.post("/api/v1/transport/scans", {"token": token}, format="json")

    assert response.status_code == 201
    assert response.json()["data"]["accepted"] is True
    assert response.json()["data"]["student_user_code"] == "STU-001"
    assert ScanLog.objects.filter(pass_id=bus_pass.id, accepted=True).count() == 1


def test_the_same_token_cannot_be_scanned_twice():
    """A screenshotted QR replayed at the next stop must not board again."""
    _pass(TENANT_A)
    token = _client(TENANT_A).get("/api/v1/transport/passes/mine/qr").json()["data"]["token"]
    driver = _client(TENANT_A, role="driver", sub="DRV-001")
    driver.post("/api/v1/transport/scans", {"token": token}, format="json")

    response = driver.post("/api/v1/transport/scans", {"token": token}, format="json")

    assert response.status_code == 409
    assert ScanLog.objects.filter(accepted=False).count() == 1


def test_a_tampered_token_is_rejected():
    _pass(TENANT_A)
    token = _client(TENANT_A).get("/api/v1/transport/passes/mine/qr").json()["data"]["token"]
    driver = _client(TENANT_A, role="driver", sub="DRV-001")

    response = driver.post(
        "/api/v1/transport/scans", {"token": token[:-4] + "AAAA"}, format="json"
    )

    assert response.status_code == 400


def test_a_pass_token_from_another_tenant_is_rejected():
    token = sign(
        {"kind": "bus_pass", "tenant_id": str(TENANT_B), "pass_id": str(uuid.uuid4())},
        ttl_seconds=30,
    )
    driver = _client(TENANT_A, role="driver", sub="DRV-001")

    response = driver.post("/api/v1/transport/scans", {"token": token}, format="json")

    assert response.status_code == 400


def test_students_cannot_scan():
    _pass(TENANT_A)
    token = _client(TENANT_A).get("/api/v1/transport/passes/mine/qr").json()["data"]["token"]
    other_student = _client(TENANT_A, sub="STU-002")

    response = other_student.post("/api/v1/transport/scans", {"token": token}, format="json")

    assert response.status_code == 403


def test_only_scanners_can_fetch_the_verification_key():
    assert _client(TENANT_A).get("/api/v1/transport/scan-key").status_code == 403
    assert (
        _client(TENANT_A, role="driver", sub="DRV-001")
        .get("/api/v1/transport/scan-key")
        .status_code
        == 200
    )
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd services/transport-service && python -m pytest transport/tests/test_pass_qr.py -v`
Expected: FAIL — `ImportError: cannot import name 'ScanLog'`

- [ ] **Step 3: Add the model**

Append to `services/transport-service/transport/models.py`:

```python
class ScanLog(TenantModel):
    """One gate scan of a QR pass.

    ``nonce`` is unique, which is the entire replay defense: every minted QR
    carries a fresh nonce, so a screenshot presented a second time collides
    here and is refused. Rejected scans are recorded too — a burst of them is
    exactly the signal that someone is passing a screenshot around.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pass_id = models.UUIDField()
    student_user_code = models.CharField(max_length=30)
    scanned_by = models.CharField(max_length=30)
    nonce = models.CharField(max_length=64, unique=True)
    accepted = models.BooleanField()
    reason = models.CharField(max_length=255, blank=True, default="")
    scanned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["pass_id", "scanned_at"], name="scanlog_pass_time"),
        ]

    def __str__(self):
        return f"{self.student_user_code} @ {self.scanned_at} ({'ok' if self.accepted else 'refused'})"
```

- [ ] **Step 4: Add the pass-token helper**

Create `services/transport-service/transport/pass_tokens.py`:

```python
"""Bus-pass capability tokens over the shared signer."""

from suerp_common.signed_token import sign, verify

KIND = "bus_pass"

#: Short enough that a screenshot is stale before it can be forwarded,
#: long enough that a student holding up a phone in a queue still scans.
PASS_TTL_SECONDS = 30


def mint(tenant_id, pass_id, student_user_code: str) -> str:
    return sign(
        {
            "kind": KIND,
            "tenant_id": str(tenant_id),
            "pass_id": str(pass_id),
            "student_user_code": student_user_code,
        },
        ttl_seconds=PASS_TTL_SECONDS,
    )


def read(token: str) -> dict:
    return verify(token, expected_kind=KIND)
```

- [ ] **Step 5: Add the views**

Append to `services/transport-service/transport/views.py`:

```python
class MyPassQrView(APIView):
    """GET /api/v1/transport/passes/mine/qr — a fresh 30-second pass token.

    The app re-requests this every 30 seconds while the QR is on screen, so
    a screenshot dies before it is useful.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        bus_pass = Pass.objects.filter(
            student_user_code=request.user.id, active=True
        ).first()
        if bus_pass is None:
            return fail("You have no active bus pass.", status=404)

        token = pass_tokens.mint(request.user.tenant_id, bus_pass.id, request.user.id)
        return ok({"token": token, "expires_in": pass_tokens.PASS_TTL_SECONDS})


class ScanKeyView(APIView):
    """GET /api/v1/transport/scan-key — verification material for scanners.

    Cached in the scanner's SecureStore at login so a gate scan needs no
    network. See the security note in the Phase 4 plan: this hands a
    symmetric key to scanner devices, and moving to an asymmetric scheme is
    the intended end state.
    """

    permission_classes = [role_required("driver", "warden", "admin")]

    def get(self, request):
        return ok({"algorithm": "HS256", "key": settings.JWT_SIGNING_KEY})


class ScanView(APIView):
    """POST /api/v1/transport/scans — record a gate scan."""

    permission_classes = [role_required("driver", "warden", "admin")]

    def post(self, request):
        token = request.data.get("token", "")
        if not token:
            return fail("A token is required.", status=400)

        try:
            claims = pass_tokens.read(token)
        except SignedTokenError as exc:
            return fail(f"Invalid pass: {exc}", status=400)

        if claims["tenant_id"] != str(request.user.tenant_id):
            return fail("Invalid pass: wrong institution.", status=400)

        try:
            with transaction.atomic():
                scan = ScanLog.objects.create(
                    tenant_id=request.user.tenant_id,
                    pass_id=claims["pass_id"],
                    student_user_code=claims["student_user_code"],
                    scanned_by=request.user.id,
                    nonce=claims["nonce"],
                    accepted=True,
                )
        except IntegrityError:
            # The nonce is already spent — this QR has been scanned before.
            ScanLog.objects.create(
                tenant_id=request.user.tenant_id,
                pass_id=claims["pass_id"],
                student_user_code=claims["student_user_code"],
                scanned_by=request.user.id,
                nonce=f"{claims['nonce']}:dup:{uuid.uuid4()}",
                accepted=False,
                reason="Pass already scanned.",
            )
            return fail("This pass has already been scanned.", status=409)

        return ok(
            {
                "accepted": scan.accepted,
                "student_user_code": scan.student_user_code,
                "scanned_at": scan.scanned_at,
            },
            message="Pass accepted.",
            status=201,
        )
```

Add the imports: `from django.conf import settings`, `from django.db import IntegrityError, transaction`, `from suerp_common.signed_token import SignedTokenError`, `from transport import pass_tokens`, plus `Pass` and `ScanLog`.

- [ ] **Step 6: Add the routes**

In `services/transport-service/transport/urls.py`:

```python
    path("passes/mine/qr", MyPassQrView.as_view(), name="my-pass-qr"),
    path("scan-key", ScanKeyView.as_view(), name="scan-key"),
    path("scans", ScanView.as_view(), name="scan-create"),
```

- [ ] **Step 7: Migrate and run the tests**

Run: `cd services/transport-service && python manage.py makemigrations transport && python -m pytest transport/tests/ -v`
Expected: the 8 new tests PASS and every pre-existing transport test still PASSES

- [ ] **Step 8: Commit**

```bash
git add services/transport-service/
git commit -m "feat(transport): add QR bus passes with replay-resistant scanning"
```

---

## Task 3: QR pass and scanner in the app

**Files:**
- Create: `mobile/su-erp-app/src/lib/device/qr.ts`
- Create: `mobile/su-erp-app/src/features/pass/usePass.ts`
- Create: `mobile/su-erp-app/app/(student)/pass.tsx`
- Create: `mobile/su-erp-app/app/(driver)/scan.tsx`
- Create: `mobile/su-erp-app/src/features/pass/__tests__/usePass.test.ts`

**Interfaces:**
- Consumes: `request`, `enqueue`.
- Produces:
  - `fetchPassToken(): Promise<{ token: string; expires_in: number }>`
  - `submitScan(token: string): Promise<ScanResult | Queued>` — queues offline
  - `verifyLocally(token: string, key: string): ScanClaims | null` — offline pre-check before queueing
  - `usePassToken()` — refetches on the token's own TTL

- [ ] **Step 1: Install the QR packages**

Run: `cd mobile/su-erp-app && npx expo install expo-camera && npm install react-native-qrcode-svg react-native-svg`

- [ ] **Step 2: Write the failing test**

Create `mobile/su-erp-app/src/features/pass/__tests__/usePass.test.ts`:

```ts
import { useConnectivity } from '@/lib/net/connectivity';

import { submitScan } from '../usePass';

jest.mock('@/lib/api/client', () => ({ request: jest.fn() }));
jest.mock('@/lib/offline/queue', () => ({ enqueue: jest.fn(async () => ({ id: 'q1' })) }));
jest.mock('@react-native-community/netinfo', () => ({ addEventListener: jest.fn(() => () => {}) }));

const { request } = jest.requireMock('@/lib/api/client');
const { enqueue } = jest.requireMock('@/lib/offline/queue');

beforeEach(() => {
  request.mockReset();
  enqueue.mockClear();
  useConnectivity.setState({ online: true });
});

test('a scan posts immediately when online', async () => {
  request.mockResolvedValue({ accepted: true, student_user_code: 'STU-001' });

  const result = await submitScan('tok');

  expect(request).toHaveBeenCalledWith(
    '/api/v1/transport/scans',
    expect.objectContaining({ method: 'POST' }),
  );
  expect(result).toEqual({ accepted: true, student_user_code: 'STU-001' });
});

test('a scan on a moving bus queues when offline', async () => {
  useConnectivity.setState({ online: false });

  const result = await submitScan('tok');

  expect(enqueue).toHaveBeenCalledWith('/api/v1/transport/scans', 'POST', { token: 'tok' });
  expect(result).toEqual({ queued: true });
  expect(request).not.toHaveBeenCalled();
});
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd mobile/su-erp-app && npx jest src/features/pass`
Expected: FAIL — module missing

- [ ] **Step 4: Write the feature module**

Create `mobile/su-erp-app/src/features/pass/usePass.ts`:

```ts
import { useQuery } from '@tanstack/react-query';

import { request } from '@/lib/api/client';
import { useConnectivity } from '@/lib/net/connectivity';
import { enqueue } from '@/lib/offline/queue';

export const PASS_TOKEN_KEY = ['transport', 'pass-token'];

export interface PassToken {
  token: string;
  expires_in: number;
}

export interface ScanResult {
  accepted: boolean;
  student_user_code: string;
  scanned_at?: string;
}

export type Queued = { queued: true };

export function fetchPassToken(): Promise<PassToken> {
  return request<PassToken>('/api/v1/transport/passes/mine/qr');
}

/**
 * The QR must re-render before its token expires, or the student holds up a
 * dead code. Refetching slightly ahead of the TTL keeps a live code on
 * screen without a visible gap.
 */
export function usePassToken() {
  return useQuery({
    queryKey: PASS_TOKEN_KEY,
    queryFn: fetchPassToken,
    refetchInterval: (query) => ((query.state.data?.expires_in ?? 30) - 5) * 1000,
    staleTime: 0,
    gcTime: 0,
  });
}

/**
 * Queueable: the gate and the moving bus are precisely where signal dies.
 * The server is still the authority on whether a nonce was already spent —
 * a queued scan that turns out to be a replay comes back 409 and the queue
 * drops it, which is the correct outcome.
 */
export async function submitScan(token: string): Promise<ScanResult | Queued> {
  if (!useConnectivity.getState().online) {
    await enqueue('/api/v1/transport/scans', 'POST', { token });
    return { queued: true };
  }

  return request<ScanResult>('/api/v1/transport/scans', {
    method: 'POST',
    body: JSON.stringify({ token }),
  });
}
```

- [ ] **Step 5: Write the student pass screen**

Create `mobile/su-erp-app/app/(student)/pass.tsx`:

```tsx
import { ActivityIndicator, Text, View } from 'react-native';
import QRCode from 'react-native-qrcode-svg';

import { usePassToken } from '@/features/pass/usePass';

export default function PassScreen() {
  const { data, isLoading, isError } = usePassToken();

  if (isLoading) {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}>
        <ActivityIndicator />
      </View>
    );
  }

  if (isError || !data) {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 }}>
        <Text style={{ textAlign: 'center' }}>
          You have no active bus pass. Book a seat and complete payment to activate one.
        </Text>
      </View>
    );
  }

  return (
    <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', gap: 24 }}>
      <QRCode value={data.token} size={260} />
      <Text style={{ color: '#6b7280' }}>Refreshes every {data.expires_in} seconds</Text>
    </View>
  );
}
```

- [ ] **Step 6: Write the driver scanner screen**

Create `mobile/su-erp-app/app/(driver)/scan.tsx`:

```tsx
import { CameraView, useCameraPermissions } from 'expo-camera';
import { useRef, useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { submitScan } from '@/features/pass/usePass';

export default function ScanScreen() {
  const [permission, requestPermission] = useCameraPermissions();
  const [result, setResult] = useState<string | null>(null);
  // The camera fires continuously while a code is in frame; without this
  // guard one pass would submit dozens of scans and burn its own nonce.
  const busy = useRef(false);

  async function onScanned({ data }: { data: string }) {
    if (busy.current) return;
    busy.current = true;

    try {
      const outcome = await submitScan(data);
      setResult(
        'queued' in outcome
          ? 'Saved offline — will sync'
          : `Accepted: ${outcome.student_user_code}`,
      );
    } catch (error) {
      setResult((error as Error).message);
    } finally {
      setTimeout(() => {
        busy.current = false;
      }, 2000);
    }
  }

  if (!permission?.granted) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', padding: 24, gap: 12 }}>
        <Text>Camera access is required to scan passes.</Text>
        <Pressable onPress={requestPermission}>
          <Text style={{ color: '#1d4ed8', fontWeight: '600' }}>Grant access</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <View style={{ flex: 1 }}>
      <CameraView
        style={{ flex: 1 }}
        barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
        onBarcodeScanned={onScanned}
      />
      {result ? (
        <View style={{ padding: 16, backgroundColor: '#111827' }}>
          <Text style={{ color: '#fff', textAlign: 'center' }}>{result}</Text>
        </View>
      ) : null}
    </View>
  );
}
```

- [ ] **Step 7: Register both screens in their tab layouts**

Add a `pass` tab to `app/(student)/_layout.tsx` (icon `qr-code`, title "Pass") and a `scan` tab to `app/(driver)/_layout.tsx` (icon `scan`, title "Scan"), matching the existing `Tabs.Screen` entries.

- [ ] **Step 8: Run the tests and typecheck**

Run: `cd mobile/su-erp-app && npx jest src/features/pass && npx tsc --noEmit`
Expected: 2 tests PASS, no type errors

- [ ] **Step 9: Commit**

```bash
git add mobile/su-erp-app/src/features/pass/ mobile/su-erp-app/app/\(student\)/pass.tsx mobile/su-erp-app/app/\(driver\)/scan.tsx mobile/su-erp-app/app/\(student\)/_layout.tsx mobile/su-erp-app/app/\(driver\)/_layout.tsx
git commit -m "feat(mobile): add rolling QR bus pass and driver scanner"
```

---

## Task 4: Geofenced attendance — backend

**Files:**
- Modify: `services/attendance-service/attendance/models.py`, `views.py`, `urls.py`, `serializers.py`
- Create: `services/attendance-service/attendance/rolling_code.py`
- Create: `services/attendance-service/attendance/tests/test_sessions.py`

**Interfaces:**
- Produces:
  - `Session` model: `id`, `course_code`, `faculty_id`, `lat`, `lng`, `radius_m`, `opened_at`, `closed_at`
  - `AttendanceMark` model: `id`, `session: FK`, `student_user_code`, `marked_at`, `distance_m`, `mock_location: bool` — unique on `(session, student_user_code)`
  - `current_code(session_id, secret) -> str` and `is_code_valid(session_id, secret, code) -> bool` in `rolling_code.py`
  - `POST /api/v1/attendance/sessions` (faculty/admin) — opens a session, returns the geofence
  - `GET /api/v1/attendance/sessions/<uuid:pk>/code` (faculty/admin) — the current rolling code
  - `POST /api/v1/attendance/sessions/<uuid:pk>/mark` (student) — body `{lat, lng, code, mock_location}`
  - `GET /api/v1/attendance/summary` (student) — attendance percentage per course

- [ ] **Step 1: Read the stub's current shape**

Run: `ls services/attendance-service/attendance/ && cat services/attendance-service/attendance/models.py`
Record what the stub model is. Replace it rather than layering on top — it is a placeholder with no domain logic.

- [ ] **Step 2: Write the failing tests**

Create `services/attendance-service/attendance/tests/test_sessions.py`:

```python
"""Geofenced attendance: session, rolling code, and proxy resistance."""

import uuid

import pytest
from attendance.models import AttendanceMark, Session
from attendance.rolling_code import current_code

pytestmark = pytest.mark.django_db

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()

# A classroom and a point ~400 m away, well outside any sane radius.
ROOM = {"lat": "12.971599", "lng": "77.594566"}
FAR_AWAY = {"lat": "12.975200", "lng": "77.594566"}


def _client(tenant_id, role="student", sub="STU-001"):
    from tests.helpers import auth_client  # noqa: PLC0415

    return auth_client(tenant_id=tenant_id, role=role, sub=sub)


def _open_session(tenant_id, faculty="FAC-001"):
    client = _client(tenant_id, role="faculty", sub=faculty)
    return client.post(
        "/api/v1/attendance/sessions",
        {"course_code": "CS101", **ROOM, "radius_m": 50},
        format="json",
    ).json()["data"]


def _mark(client, session_id, code, position=ROOM, mock_location=False):
    return client.post(
        f"/api/v1/attendance/sessions/{session_id}/mark",
        {**position, "code": code, "mock_location": mock_location},
        format="json",
    )


def test_faculty_opens_a_session_and_gets_the_geofence():
    session = _open_session(TENANT_A)

    assert session["radius_m"] == 50
    assert session["closed_at"] is None


def test_students_cannot_open_a_session():
    client = _client(TENANT_A)

    response = client.post(
        "/api/v1/attendance/sessions",
        {"course_code": "CS101", **ROOM, "radius_m": 50},
        format="json",
    )

    assert response.status_code == 403


def test_a_student_inside_the_geofence_with_the_current_code_is_marked():
    session = _open_session(TENANT_A)
    code = current_code(session["id"])

    response = _mark(_client(TENANT_A), session["id"], code)

    assert response.status_code == 201
    assert AttendanceMark.objects.count() == 1


def test_a_student_outside_the_geofence_is_refused():
    session = _open_session(TENANT_A)
    code = current_code(session["id"])

    response = _mark(_client(TENANT_A), session["id"], code, position=FAR_AWAY)

    assert response.status_code == 400
    assert AttendanceMark.objects.count() == 0


def test_a_stale_code_is_refused():
    """The whole point: being in the room is not enough without the code."""
    session = _open_session(TENANT_A)

    response = _mark(_client(TENANT_A), session["id"], "000000")

    assert response.status_code == 400
    assert AttendanceMark.objects.count() == 0


def test_a_student_cannot_mark_twice():
    session = _open_session(TENANT_A)
    code = current_code(session["id"])
    client = _client(TENANT_A)
    _mark(client, session["id"], code)

    response = _mark(client, session["id"], code)

    assert response.status_code == 409
    assert AttendanceMark.objects.count() == 1


def test_a_mock_location_report_is_recorded_but_refused():
    session = _open_session(TENANT_A)
    code = current_code(session["id"])

    response = _mark(_client(TENANT_A), session["id"], code, mock_location=True)

    assert response.status_code == 400


def test_marking_a_closed_session_is_refused():
    session = _open_session(TENANT_A)
    faculty = _client(TENANT_A, role="faculty", sub="FAC-001")
    faculty.post(f"/api/v1/attendance/sessions/{session['id']}/close", format="json")
    code = current_code(session["id"])

    response = _mark(_client(TENANT_A), session["id"], code)

    assert response.status_code == 400


def test_sessions_do_not_leak_across_tenants():
    session = _open_session(TENANT_A)
    code = current_code(session["id"])

    response = _mark(_client(TENANT_B, sub="STU-999"), session["id"], code)

    assert response.status_code == 404
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd services/attendance-service && python -m pytest attendance/tests/test_sessions.py -v`
Expected: FAIL — `ImportError: cannot import name 'Session'`

- [ ] **Step 4: Write the rolling code module**

Create `services/attendance-service/attendance/rolling_code.py`:

```python
"""Time-bucketed codes displayed on the faculty's dashboard.

A code derived from (session, current 15-second bucket) means a student who
photographs the projector and sends it to a friend across campus has sent
something that is already dead — and the geofence stops the friend anyway.
Two independent checks, each cheap.
"""

import hashlib
import hmac
import time

from django.conf import settings

#: Short enough that a forwarded screenshot expires in transit; long enough
#: that a student typing it in is not racing a clock.
CODE_PERIOD_SECONDS = 15
CODE_DIGITS = 6


def _bucket(at: float | None = None) -> int:
    return int((at if at is not None else time.time()) // CODE_PERIOD_SECONDS)


def _code_for_bucket(session_id, bucket: int) -> str:
    message = f"{session_id}:{bucket}".encode()
    digest = hmac.new(settings.JWT_SIGNING_KEY.encode(), message, hashlib.sha256).digest()
    number = int.from_bytes(digest[:4], "big") % (10**CODE_DIGITS)
    return str(number).zfill(CODE_DIGITS)


def current_code(session_id) -> str:
    return _code_for_bucket(session_id, _bucket())


def is_code_valid(session_id, code: str) -> bool:
    """Accepts the current bucket and the previous one.

    The one-bucket grace exists because a student can read a code at 14.9
    seconds and submit at 15.1 — refusing that would make the feature feel
    broken for a reason the student cannot see.
    """
    now = _bucket()
    return any(
        hmac.compare_digest(_code_for_bucket(session_id, bucket), code)
        for bucket in (now, now - 1)
    )
```

- [ ] **Step 5: Write the models**

Replace the stub in `services/attendance-service/attendance/models.py`:

```python
"""Attendance sessions and marks.

A Session is one class meeting, pinned to a location. A student may mark
attendance only from inside that circle, with the code currently on the
faculty's screen, once. Those three constraints together are what make
proxy attendance meaningfully harder than "a friend taps a button".
"""

import math
import uuid

from django.db import models
from suerp_common.tenancy import TenantModel

EARTH_RADIUS_M = 6_371_000


def haversine_metres(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance. Exact enough at classroom scale, and it needs
    no PostGIS — adding a spatial extension for one circle test would be a
    large dependency for a small question."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


class Session(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course_code = models.CharField(max_length=50)
    faculty_id = models.CharField(max_length=30)
    lat = models.DecimalField(max_digits=9, decimal_places=6)
    lng = models.DecimalField(max_digits=9, decimal_places=6)
    radius_m = models.PositiveSmallIntegerField(default=50)
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["course_code", "opened_at"], name="session_course_time"),
        ]

    @property
    def is_open(self) -> bool:
        return self.closed_at is None

    def contains(self, lat: float, lng: float) -> float | None:
        """Distance in metres if inside the fence, else None."""
        distance = haversine_metres(float(self.lat), float(self.lng), lat, lng)
        return distance if distance <= self.radius_m else None

    def __str__(self):
        return f"{self.course_code} @ {self.opened_at}"


class AttendanceMark(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="marks")
    student_user_code = models.CharField(max_length=30)
    distance_m = models.FloatField()
    #: Reported by the device. Recorded even on refusal, because a pattern of
    #: mock-location attempts is itself worth seeing.
    mock_location = models.BooleanField(default=False)
    marked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session", "student_user_code"], name="one_mark_per_student_per_session"
            ),
        ]

    def __str__(self):
        return f"{self.student_user_code} @ {self.session_id}"
```

- [ ] **Step 6: Write the serializers and views**

Create the serializers in `services/attendance-service/attendance/serializers.py`:

```python
from attendance.models import AttendanceMark, Session
from rest_framework import serializers


class SessionCreateSerializer(serializers.Serializer):
    course_code = serializers.CharField(max_length=50)
    lat = serializers.DecimalField(max_digits=9, decimal_places=6)
    lng = serializers.DecimalField(max_digits=9, decimal_places=6)
    radius_m = serializers.IntegerField(min_value=10, max_value=500, default=50)


class SessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Session
        fields = ["id", "course_code", "faculty_id", "lat", "lng", "radius_m", "opened_at", "closed_at"]
        read_only_fields = fields


class MarkRequestSerializer(serializers.Serializer):
    lat = serializers.FloatField()
    lng = serializers.FloatField()
    code = serializers.CharField(max_length=10)
    mock_location = serializers.BooleanField(default=False)


class AttendanceMarkSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttendanceMark
        fields = ["id", "session", "student_user_code", "distance_m", "mock_location", "marked_at"]
        read_only_fields = fields
```

Write the views in `services/attendance-service/attendance/views.py`:

```python
"""Attendance session lifecycle and geofenced marking."""

from attendance.models import AttendanceMark, Session
from attendance.rolling_code import CODE_PERIOD_SECONDS, current_code, is_code_valid
from attendance.serializers import (
    AttendanceMarkSerializer,
    MarkRequestSerializer,
    SessionCreateSerializer,
    SessionSerializer,
)
from django.db import IntegrityError
from django.db.models import Count
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from suerp_common.envelope import fail, ok
from suerp_common.permissions import role_required


class SessionCreateView(APIView):
    """POST /api/v1/attendance/sessions — faculty opens a class meeting."""

    permission_classes = [role_required("faculty", "admin")]

    def post(self, request):
        serializer = SessionCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid session.", errors=serializer.errors, status=400)

        session = Session.objects.create(
            tenant_id=request.user.tenant_id,
            faculty_id=request.user.id,
            **serializer.validated_data,
        )
        return ok(SessionSerializer(session).data, message="Session opened.", status=201)


class SessionCloseView(APIView):
    permission_classes = [role_required("faculty", "admin")]

    def post(self, request, pk):
        try:
            session = Session.objects.get(pk=pk)
        except Session.DoesNotExist:
            return fail("Session not found.", status=404)

        if session.closed_at is not None:
            return fail("Session is already closed.", status=400)

        session.closed_at = timezone.now()
        session.save(update_fields=["closed_at"])
        return ok(SessionSerializer(session).data, message="Session closed.")


class SessionCodeView(APIView):
    """GET /api/v1/attendance/sessions/<id>/code — the code to display."""

    permission_classes = [role_required("faculty", "admin")]

    def get(self, request, pk):
        try:
            session = Session.objects.get(pk=pk)
        except Session.DoesNotExist:
            return fail("Session not found.", status=404)

        return ok({"code": current_code(session.id), "rotates_in": CODE_PERIOD_SECONDS})


class MarkAttendanceView(APIView):
    """POST /api/v1/attendance/sessions/<id>/mark — a student checks in.

    Three gates, in the order that fails cheapest first: the session must be
    open, the device must not be reporting a mocked location, the code must
    be current, and the device must be inside the fence.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        serializer = MarkRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid mark request.", errors=serializer.errors, status=400)

        data = serializer.validated_data

        try:
            session = Session.objects.get(pk=pk)
        except Session.DoesNotExist:
            return fail("Session not found.", status=404)

        if not session.is_open:
            return fail("This session is closed.", status=400)

        if data["mock_location"]:
            return fail("Attendance cannot be marked from a mocked location.", status=400)

        if not is_code_valid(session.id, data["code"]):
            return fail("That code has expired. Use the code on screen now.", status=400)

        distance = session.contains(data["lat"], data["lng"])
        if distance is None:
            return fail("You are not in the classroom.", status=400)

        try:
            mark = AttendanceMark.objects.create(
                tenant_id=request.user.tenant_id,
                session=session,
                student_user_code=request.user.id,
                distance_m=distance,
                mock_location=False,
            )
        except IntegrityError:
            return fail("You have already marked attendance for this session.", status=409)

        return ok(AttendanceMarkSerializer(mark).data, message="Attendance marked.", status=201)


class AttendanceSummaryView(APIView):
    """GET /api/v1/attendance/summary — the caller's percentage per course."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        student = request.user.id
        held = (
            Session.objects.values("course_code")
            .annotate(sessions=Count("id"))
            .order_by("course_code")
        )
        attended = {
            row["session__course_code"]: row["marks"]
            for row in AttendanceMark.objects.filter(student_user_code=student)
            .values("session__course_code")
            .annotate(marks=Count("id"))
        }

        summary = []
        for row in held:
            course = row["course_code"]
            present = attended.get(course, 0)
            summary.append(
                {
                    "course_code": course,
                    "held": row["sessions"],
                    "attended": present,
                    "percentage": round(100 * present / row["sessions"], 1),
                }
            )

        return ok(summary)
```

- [ ] **Step 7: Wire the routes**

Replace `services/attendance-service/attendance/urls.py`:

```python
"""Attendance endpoints, included under /api/v1/attendance/ from config.urls."""

from attendance.views import (
    AttendanceSummaryView,
    MarkAttendanceView,
    SessionCloseView,
    SessionCodeView,
    SessionCreateView,
)
from django.urls import path

urlpatterns = [
    path("sessions", SessionCreateView.as_view(), name="session-create"),
    path("sessions/<uuid:pk>/close", SessionCloseView.as_view(), name="session-close"),
    path("sessions/<uuid:pk>/code", SessionCodeView.as_view(), name="session-code"),
    path("sessions/<uuid:pk>/mark", MarkAttendanceView.as_view(), name="session-mark"),
    path("summary", AttendanceSummaryView.as_view(), name="attendance-summary"),
]
```

- [ ] **Step 8: Migrate and run the tests**

Run: `cd services/attendance-service && python manage.py makemigrations attendance && python -m pytest attendance/ -v`
Expected: all 9 tests PASS

- [ ] **Step 9: Commit**

```bash
git add services/attendance-service/
git commit -m "feat(attendance): build out geofenced sessions with rolling codes"
```

---

## Task 5: Attendance in the app

**Files:**
- Create: `mobile/su-erp-app/src/lib/device/geofence.ts`
- Create: `mobile/su-erp-app/src/features/attendance/useAttendance.ts`
- Create: `mobile/su-erp-app/app/(student)/attendance.tsx`
- Create: `mobile/su-erp-app/src/features/attendance/__tests__/useAttendance.test.ts`
- Create: `shared/api-types/attendance.ts`

**Interfaces:**
- Consumes: `request`, `enqueue`, `watchPosition` / `requestPermission` (Phase 3 Task 5).
- Produces:
  - `getCurrentPosition(): Promise<{ lat: number; lng: number; mocked: boolean }>`
  - `markAttendance(sessionId, code): Promise<Mark | Queued>` — queues offline
  - `fetchSummary(): Promise<CourseSummary[]>`

- [ ] **Step 1: Add the shared types**

Create `shared/api-types/attendance.ts`:

```ts
export interface AttendanceSession {
  id: string;
  course_code: string;
  faculty_id: string;
  lat: string;
  lng: string;
  radius_m: number;
  opened_at: string;
  closed_at: string | null;
}

export interface AttendanceMark {
  id: string;
  session: string;
  student_user_code: string;
  distance_m: number;
  mock_location: boolean;
  marked_at: string;
}

export interface CourseSummary {
  course_code: string;
  held: number;
  attended: number;
  percentage: number;
}
```

Add `export * from './attendance';` to `shared/api-types/index.ts`.

- [ ] **Step 2: Write the failing test**

Create `mobile/su-erp-app/src/features/attendance/__tests__/useAttendance.test.ts`:

```ts
import { useConnectivity } from '@/lib/net/connectivity';

import { markAttendance } from '../useAttendance';

jest.mock('@/lib/api/client', () => ({ request: jest.fn() }));
jest.mock('@/lib/offline/queue', () => ({ enqueue: jest.fn(async () => ({ id: 'q1' })) }));
jest.mock('@/lib/device/geofence', () => ({
  getCurrentPosition: jest.fn(async () => ({ lat: 12.971599, lng: 77.594566, mocked: false })),
}));
jest.mock('@react-native-community/netinfo', () => ({ addEventListener: jest.fn(() => () => {}) }));

const { request } = jest.requireMock('@/lib/api/client');
const { enqueue } = jest.requireMock('@/lib/offline/queue');
const { getCurrentPosition } = jest.requireMock('@/lib/device/geofence');

beforeEach(() => {
  request.mockReset();
  enqueue.mockClear();
  getCurrentPosition.mockResolvedValue({ lat: 12.971599, lng: 77.594566, mocked: false });
  useConnectivity.setState({ online: true });
});

test('marking sends the position and the code', async () => {
  request.mockResolvedValue({ id: 'm1' });

  await markAttendance('s1', '123456');

  const body = JSON.parse(request.mock.calls[0][1].body);
  expect(body).toEqual({
    lat: 12.971599,
    lng: 77.594566,
    code: '123456',
    mock_location: false,
  });
});

test('a mocked location is reported honestly rather than hidden', async () => {
  getCurrentPosition.mockResolvedValue({ lat: 12.9, lng: 77.5, mocked: true });
  request.mockResolvedValue({ id: 'm1' });

  await markAttendance('s1', '123456').catch(() => undefined);

  const body = JSON.parse(request.mock.calls[0][1].body);
  expect(body.mock_location).toBe(true);
});

test('marking queues in a dead-zone classroom', async () => {
  useConnectivity.setState({ online: false });

  const result = await markAttendance('s1', '123456');

  expect(enqueue).toHaveBeenCalledWith(
    '/api/v1/attendance/sessions/s1/mark',
    'POST',
    expect.objectContaining({ code: '123456' }),
  );
  expect(result).toEqual({ queued: true });
});
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd mobile/su-erp-app && npx jest src/features/attendance`
Expected: FAIL — module missing

- [ ] **Step 4: Write the geofence module**

Create `mobile/su-erp-app/src/lib/device/geofence.ts`:

```ts
import * as Location from 'expo-location';

export interface Position {
  lat: number;
  lng: number;
  /** Android reports this directly; iOS has no equivalent and returns false. */
  mocked: boolean;
}

export async function getCurrentPosition(): Promise<Position> {
  const { status } = await Location.requestForegroundPermissionsAsync();
  if (status !== 'granted') throw new Error('Location permission is required.');

  const position = await Location.getCurrentPositionAsync({
    accuracy: Location.Accuracy.High,
  });

  return {
    lat: position.coords.latitude,
    lng: position.coords.longitude,
    // Reported to the server rather than silently dropped: the server
    // refuses the mark AND records the attempt, which is the useful signal.
    mocked: Boolean((position as { mocked?: boolean }).mocked),
  };
}
```

- [ ] **Step 5: Write the feature module**

Create `mobile/su-erp-app/src/features/attendance/useAttendance.ts`:

```ts
import type { AttendanceMark, CourseSummary } from '@api-types/index';
import { useMutation, useQuery } from '@tanstack/react-query';

import { request } from '@/lib/api/client';
import { getCurrentPosition } from '@/lib/device/geofence';
import { useConnectivity } from '@/lib/net/connectivity';
import { enqueue } from '@/lib/offline/queue';

export const SUMMARY_KEY = ['attendance', 'summary'];

export type Queued = { queued: true };

export function fetchSummary(): Promise<CourseSummary[]> {
  return request<CourseSummary[]>('/api/v1/attendance/summary');
}

export function useAttendanceSummary() {
  return useQuery({ queryKey: SUMMARY_KEY, queryFn: fetchSummary });
}

/**
 * Queueable, with one caveat worth knowing: a queued mark carries the code
 * that was current when it was captured, and the server accepts only the
 * current or previous bucket. So a mark queued for more than ~30 seconds
 * will be refused on replay and dropped. That is deliberate — accepting an
 * old code would reopen exactly the proxy hole the code exists to close.
 * The queue still helps the common case: a brief signal drop at submit time.
 */
export async function markAttendance(
  sessionId: string,
  code: string,
): Promise<AttendanceMark | Queued> {
  const position = await getCurrentPosition();
  const body = {
    lat: position.lat,
    lng: position.lng,
    code,
    mock_location: position.mocked,
  };
  const path = `/api/v1/attendance/sessions/${sessionId}/mark`;

  if (!useConnectivity.getState().online) {
    await enqueue(path, 'POST', body);
    return { queued: true };
  }

  return request<AttendanceMark>(path, { method: 'POST', body: JSON.stringify(body) });
}

export function useMarkAttendance() {
  return useMutation({
    mutationFn: ({ sessionId, code }: { sessionId: string; code: string }) =>
      markAttendance(sessionId, code),
  });
}
```

- [ ] **Step 6: Write the screen**

Create `mobile/su-erp-app/app/(student)/attendance.tsx` with two sections:
1. A "Mark attendance" form taking the session id (scanned from the faculty's QR or typed) and the 6-digit code, calling `useMarkAttendance()`. Show the failure reason verbatim — "You are not in the classroom" and "That code has expired" are both actionable, and collapsing them into "failed" would leave the student stuck.
2. A summary list from `useAttendanceSummary()`, one row per course showing `attended/held` and the percentage, coloured red below 75%.

Follow the layout conventions of `app/(student)/fees.tsx`, and register an `attendance` tab in `app/(student)/_layout.tsx`.

- [ ] **Step 7: Run the tests and typecheck**

Run: `cd mobile/su-erp-app && npx jest src/features/attendance && npx tsc --noEmit`
Expected: 3 tests PASS, no type errors

- [ ] **Step 8: Commit**

```bash
git add mobile/su-erp-app/src/features/attendance/ mobile/su-erp-app/src/lib/device/geofence.ts mobile/su-erp-app/app/\(student\)/attendance.tsx shared/api-types/attendance.ts
git commit -m "feat(mobile): add geofenced attendance marking and summary"
```

---

## Task 6: Camera grievance with auto-purging media

**Files:**
- Modify: `services/grievance-service/grievance/models.py`, `views.py`, `urls.py`, `serializers.py`
- Modify: `services/grievance-service/grievance/tasks.py`, `config/settings.py`
- Create: `services/grievance-service/grievance/tests/test_media_purge.py`

**Interfaces:**
- Produces:
  - `TicketMedia` model: `id`, `ticket: FK`, `file`, `sha256`, `captured_at`, `expires_at: datetime|None`, `purged_at: datetime|None`
  - `POST /api/v1/grievance/<uuid:ticket_id>/media` — upload (owner only)
  - `GET /api/v1/grievance/<uuid:ticket_id>/media` — list, showing purged entries as metadata only
  - `purge_expired_media_task()` — celery-beat, deletes blobs past `expires_at`
  - Resolving a ticket stamps `expires_at = now + 7 days` on its media

- [ ] **Step 1: Read the existing beat schedule**

Run: `grep -n "CELERY_BEAT_SCHEDULE" -A 15 services/grievance-service/config/settings.py` and `cat services/grievance-service/grievance/tasks.py`
Record the existing task registration style so the purge task matches it.

- [ ] **Step 2: Write the failing tests**

Create `services/grievance-service/grievance/tests/test_media_purge.py`:

```python
"""Grievance media retention: blobs die 7 days after resolution, metadata lives on."""

import uuid

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from grievance.models import Ticket, TicketMedia
from grievance.tasks import purge_expired_media_task

pytestmark = pytest.mark.django_db

TENANT_A = uuid.uuid4()


def _client(tenant_id, role="student", sub="STU-001"):
    from tests.helpers import auth_client  # noqa: PLC0415

    return auth_client(tenant_id=tenant_id, role=role, sub=sub)


def _ticket(tenant_id, status="open", raised_by="STU-001"):
    return Ticket.objects.create(
        tenant_id=tenant_id,
        category="hostel",
        description="Broken fan",
        raised_by=raised_by,
        status=status,
    )


def _upload(client, ticket_id):
    return client.post(
        f"/api/v1/grievance/{ticket_id}/media",
        {"file": SimpleUploadedFile("fan.jpg", b"fake-image-bytes", content_type="image/jpeg")},
        format="multipart",
    )


def test_a_student_attaches_a_photo_to_their_own_ticket():
    ticket = _ticket(TENANT_A)

    response = _upload(_client(TENANT_A), ticket.id)

    assert response.status_code == 201
    assert TicketMedia.objects.filter(ticket=ticket).count() == 1
    assert TicketMedia.objects.get(ticket=ticket).sha256


def test_another_student_cannot_attach_to_someone_elses_ticket():
    ticket = _ticket(TENANT_A, raised_by="STU-001")

    response = _upload(_client(TENANT_A, sub="STU-002"), ticket.id)

    assert response.status_code == 403


def test_resolving_a_ticket_schedules_its_media_for_purge():
    ticket = _ticket(TENANT_A)
    _upload(_client(TENANT_A), ticket.id)

    warden = _client(TENANT_A, role="warden", sub="WRD-001")
    warden.patch(f"/api/v1/grievance/{ticket.id}/status", {"status": "resolved"}, format="json")

    media = TicketMedia.objects.get(ticket=ticket)
    assert media.expires_at is not None
    assert (media.expires_at - timezone.now()).days >= 6


def test_the_sweep_leaves_media_inside_the_grace_window():
    ticket = _ticket(TENANT_A)
    _upload(_client(TENANT_A), ticket.id)
    TicketMedia.objects.update(expires_at=timezone.now() + timezone.timedelta(days=3))

    purge_expired_media_task()

    media = TicketMedia.objects.get(ticket=ticket)
    assert media.purged_at is None
    assert media.file


def test_the_sweep_deletes_the_blob_but_keeps_the_metadata():
    ticket = _ticket(TENANT_A)
    _upload(_client(TENANT_A), ticket.id)
    original = TicketMedia.objects.get(ticket=ticket)
    original_hash = original.sha256
    TicketMedia.objects.update(expires_at=timezone.now() - timezone.timedelta(seconds=1))

    purge_expired_media_task()

    media = TicketMedia.objects.get(ticket=ticket)
    assert media.purged_at is not None
    assert not media.file
    # The audit trail survives the evidence.
    assert media.sha256 == original_hash
    assert media.captured_at is not None


def test_purging_twice_is_harmless():
    ticket = _ticket(TENANT_A)
    _upload(_client(TENANT_A), ticket.id)
    TicketMedia.objects.update(expires_at=timezone.now() - timezone.timedelta(seconds=1))
    purge_expired_media_task()
    first_purge = TicketMedia.objects.get(ticket=ticket).purged_at

    purge_expired_media_task()

    assert TicketMedia.objects.get(ticket=ticket).purged_at == first_purge


def test_the_media_list_shows_purged_entries_as_metadata():
    ticket = _ticket(TENANT_A)
    _upload(_client(TENANT_A), ticket.id)
    TicketMedia.objects.update(expires_at=timezone.now() - timezone.timedelta(seconds=1))
    purge_expired_media_task()

    response = _client(TENANT_A).get(f"/api/v1/grievance/{ticket.id}/media")

    assert response.status_code == 200
    entry = response.json()["data"][0]
    assert entry["purged_at"] is not None
    assert entry["url"] is None
    assert entry["sha256"]
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd services/grievance-service && python -m pytest grievance/tests/test_media_purge.py -v`
Expected: FAIL — `ImportError: cannot import name 'TicketMedia'`

- [ ] **Step 4: Add the model**

Append to `services/grievance-service/grievance/models.py`:

```python
#: How long evidence survives after a ticket is resolved. Long enough that a
#: student who disagrees with the resolution can still point at the photo;
#: short enough that the platform is not indefinitely holding images of
#: people's rooms. See the mobile spec's retention rule.
MEDIA_RETENTION_DAYS = 7


class TicketMedia(TenantModel):
    """A photo or short video attached to a grievance.

    The blob is deliberately temporary and the metadata is not. Seven days
    after the ticket is resolved a sweep deletes the file and stamps
    ``purged_at``, leaving ``sha256`` and ``captured_at`` behind — so the log
    can still say "three attachments, purged on the 9th" without the platform
    holding the images forever.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="media")
    file = models.FileField(upload_to="grievance-media/", blank=True)
    sha256 = models.CharField(max_length=64)
    captured_at = models.DateTimeField()
    #: Null until the ticket resolves — an open ticket's evidence never expires.
    expires_at = models.DateTimeField(null=True, blank=True)
    purged_at = models.DateTimeField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["expires_at", "purged_at"], name="media_purge_sweep"),
        ]

    def __str__(self):
        state = "purged" if self.purged_at else "held"
        return f"media({self.ticket_id}, {state})"
```

- [ ] **Step 5: Write the purge task**

Append to `services/grievance-service/grievance/tasks.py`:

```python
@shared_task
def purge_expired_media_task():
    """Delete grievance blobs whose retention window has closed.

    Runs on the same beat that drains the outbox. Deleting the file but
    keeping the row is the whole point: the metadata is the audit trail, and
    an already-purged row is skipped, so a repeated sweep is a no-op.
    """
    from django.utils import timezone

    from grievance.models import TicketMedia

    now = timezone.now()
    expired = TicketMedia.objects.filter(
        expires_at__isnull=False, expires_at__lte=now, purged_at__isnull=True
    )

    purged = 0
    for media in expired:
        if media.file:
            media.file.delete(save=False)
        media.purged_at = now
        media.save(update_fields=["file", "purged_at"])
        purged += 1

    return {"purged": purged}
```

Register it in `services/grievance-service/config/settings.py` inside the existing `CELERY_BEAT_SCHEDULE`:

```python
    "purge-expired-grievance-media": {
        "task": "grievance.tasks.purge_expired_media_task",
        # Hourly is ample for a 7-day window and keeps the sweep cheap.
        "schedule": 3600.0,
    },
```

- [ ] **Step 6: Stamp `expires_at` on resolution**

In `services/grievance-service/grievance/views.py`, inside `GrievanceStatusView.patch` (Phase 3 Task 3), replace the save block with:

```python
        ticket.status = new_status
        ticket.save(update_fields=["status"])

        if new_status == Ticket.Status.RESOLVED:
            # Start the retention clock now rather than at upload time —
            # evidence on an unresolved ticket must never expire.
            ticket.media.filter(expires_at__isnull=True).update(
                expires_at=timezone.now() + timezone.timedelta(days=MEDIA_RETENTION_DAYS)
            )
```

Add `MEDIA_RETENTION_DAYS` and `timezone` to the imports.

- [ ] **Step 7: Add the media endpoints**

Append the upload and list views to `services/grievance-service/grievance/views.py`:

```python
class TicketMediaView(APIView):
    """POST/GET /api/v1/grievance/<id>/media — evidence attached to a ticket.

    Upload is restricted to the ticket's author: a photo of someone's room
    is not something another student should be able to bolt onto their
    complaint.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def _ticket_or_none(self, ticket_id):
        try:
            return Ticket.objects.get(id=ticket_id)
        except Ticket.DoesNotExist:
            return None

    def post(self, request, ticket_id):
        ticket = self._ticket_or_none(ticket_id)
        if ticket is None:
            return fail("Grievance not found.", status=404)

        if str(ticket.raised_by) != str(request.user.id):
            return fail("You can only attach media to your own grievance.", status=403)

        upload = request.FILES.get("file")
        if upload is None:
            return fail("A file is required.", status=400)

        digest = hashlib.sha256()
        for chunk in upload.chunks():
            digest.update(chunk)
        upload.seek(0)

        media = TicketMedia.objects.create(
            tenant_id=request.user.tenant_id,
            ticket=ticket,
            file=upload,
            sha256=digest.hexdigest(),
            captured_at=timezone.now(),
        )
        return ok(TicketMediaSerializer(media).data, message="Attached.", status=201)

    def get(self, request, ticket_id):
        ticket = self._ticket_or_none(ticket_id)
        if ticket is None:
            return fail("Grievance not found.", status=404)

        role = getattr(request.user, "role", None)
        if role not in _PRIVILEGED_ROLES and str(ticket.raised_by) != str(request.user.id):
            return fail("Not permitted to view this grievance.", status=403)

        return ok(TicketMediaSerializer(ticket.media.all(), many=True).data)
```

Add the serializer to `services/grievance-service/grievance/serializers.py`:

```python
class TicketMediaSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = TicketMedia
        fields = ["id", "url", "sha256", "captured_at", "expires_at", "purged_at"]
        read_only_fields = fields

    def get_url(self, obj):
        """None once purged — the row survives, the file does not."""
        return obj.file.url if obj.file else None
```

Add the route in `services/grievance-service/grievance/urls.py`:

```python
    path("grievance/<uuid:ticket_id>/media", TicketMediaView.as_view(), name="grievance-media"),
```

Add the imports: `hashlib`, `MultiPartParser`/`FormParser`, `TicketMedia`, `TicketMediaSerializer`.

- [ ] **Step 8: Migrate and run the tests**

Run: `cd services/grievance-service && python manage.py makemigrations grievance && python -m pytest grievance/ -v`
Expected: the 7 new tests PASS and every pre-existing grievance test still PASSES

- [ ] **Step 9: Commit**

```bash
git add services/grievance-service/
git commit -m "feat(grievance): add photo evidence with a 7-day post-resolution purge"
```

---

## Task 7: Camera capture in the app

**Files:**
- Create: `mobile/su-erp-app/src/lib/device/camera.ts`
- Create: `mobile/su-erp-app/src/lib/offline/mediaQueue.ts`
- Modify: `mobile/su-erp-app/app/(student)/grievance.tsx`
- Create: `mobile/su-erp-app/src/lib/offline/__tests__/mediaQueue.test.ts`

**Interfaces:**
- Consumes: `request`, the SQLite store pattern from `src/lib/offline/queue.ts`.
- Produces:
  - `capturePhoto(): Promise<{ uri: string } | null>`
  - `enqueueMedia(ticketId: string, uri: string): Promise<void>`
  - `replayMedia(): Promise<{ sent: number; failed: number }>` — uploads, then deletes the local file only after a 201

- [ ] **Step 1: Write the failing test**

Create `mobile/su-erp-app/src/lib/offline/__tests__/mediaQueue.test.ts`:

```ts
import { createMemoryMediaStore, enqueueMedia, replayMedia, setMediaStore } from '../mediaQueue';

jest.mock('@/lib/api/client', () => ({ request: jest.fn() }));
jest.mock('expo-file-system', () => ({ deleteAsync: jest.fn(async () => {}) }));

const { request } = jest.requireMock('@/lib/api/client');
const { deleteAsync } = jest.requireMock('expo-file-system');

beforeEach(() => {
  setMediaStore(createMemoryMediaStore());
  request.mockReset();
  deleteAsync.mockClear();
});

test('a successful upload removes the local file', async () => {
  request.mockResolvedValue({ id: 'm1' });
  await enqueueMedia('t1', 'file:///tmp/fan.jpg');

  const result = await replayMedia();

  expect(result.sent).toBe(1);
  expect(deleteAsync).toHaveBeenCalledWith('file:///tmp/fan.jpg', { idempotent: true });
});

test('a failed upload keeps the file for the next attempt', async () => {
  request.mockRejectedValue(new Error('network down'));
  await enqueueMedia('t1', 'file:///tmp/fan.jpg');

  const result = await replayMedia();

  expect(result.failed).toBe(1);
  expect(deleteAsync).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd mobile/su-erp-app && npx jest src/lib/offline/__tests__/mediaQueue.test.ts`
Expected: FAIL — module missing

- [ ] **Step 3: Write the camera module**

Run: `cd mobile/su-erp-app && npx expo install expo-image-picker expo-file-system`

Create `mobile/su-erp-app/src/lib/device/camera.ts`:

```ts
import * as ImagePicker from 'expo-image-picker';

/** Keeps uploads small enough to survive a campus connection. */
const QUALITY = 0.6;

export async function capturePhoto(): Promise<{ uri: string } | null> {
  const permission = await ImagePicker.requestCameraPermissionsAsync();
  if (!permission.granted) throw new Error('Camera access is required to attach a photo.');

  const result = await ImagePicker.launchCameraAsync({
    mediaTypes: ImagePicker.MediaTypeOptions.Images,
    quality: QUALITY,
    exif: false,
  });

  if (result.canceled) return null;
  return { uri: result.assets[0].uri };
}
```

- [ ] **Step 4: Write the media queue**

Create `mobile/su-erp-app/src/lib/offline/mediaQueue.ts`:

```ts
import * as FileSystem from 'expo-file-system';

import { request } from '@/lib/api/client';

/**
 * Photos are queued separately from JSON mutations because they are large,
 * live on the filesystem rather than in the row, and must not be deleted
 * locally until the server has confirmed receipt.
 */
export interface PendingMedia {
  id: string;
  ticketId: string;
  uri: string;
  attempts: number;
}

export interface MediaStore {
  insert(item: PendingMedia): Promise<void>;
  all(): Promise<PendingMedia[]>;
  update(item: PendingMedia): Promise<void>;
  remove(id: string): Promise<void>;
}

export function createMemoryMediaStore(): MediaStore {
  let rows: PendingMedia[] = [];
  return {
    async insert(item) {
      rows.push(item);
    },
    async all() {
      return [...rows];
    },
    async update(item) {
      rows = rows.map((r) => (r.id === item.id ? item : r));
    },
    async remove(id) {
      rows = rows.filter((r) => r.id !== id);
    },
  };
}

let store: MediaStore = createMemoryMediaStore();

export function setMediaStore(next: MediaStore): void {
  store = next;
}

function uuidv4(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export async function enqueueMedia(ticketId: string, uri: string): Promise<void> {
  await store.insert({ id: uuidv4(), ticketId, uri, attempts: 0 });
}

export async function replayMedia(): Promise<{ sent: number; failed: number }> {
  const rows = await store.all();
  let sent = 0;
  let failed = 0;

  for (const row of rows) {
    const form = new FormData();
    form.append('file', {
      uri: row.uri,
      name: 'evidence.jpg',
      type: 'image/jpeg',
    } as unknown as Blob);

    try {
      await request(`/api/v1/grievance/${row.ticketId}/media`, {
        method: 'POST',
        body: form,
        // Let the runtime set the multipart boundary — an explicit
        // application/json here would corrupt the upload.
        headers: {},
      });
      // Only now is it safe to drop the local copy.
      await FileSystem.deleteAsync(row.uri, { idempotent: true });
      await store.remove(row.id);
      sent += 1;
    } catch {
      await store.update({ ...row, attempts: row.attempts + 1 });
      failed += 1;
    }
  }

  return { sent, failed };
}
```

- [ ] **Step 5: Wire the camera into the grievance screen**

In `mobile/su-erp-app/app/(student)/grievance.tsx`, add an "Attach photo" button that calls `capturePhoto()`, holds the returned URI in state, and — after `createTicket` succeeds with a real ticket (not a `queued` marker) — calls `enqueueMedia(ticket.id, uri)` followed by `replayMedia()`. When the ticket itself was queued, hold the photo until the ticket lands; show "Photo will upload with your complaint."

Also add a retention line to each ticket row: when the API reports media with `purged_at` set, render "N attachments, purged <date>" rather than a broken thumbnail.

- [ ] **Step 6: Add the replay hook to connectivity**

In `mobile/su-erp-app/src/lib/net/connectivity.ts`, extend the reconnect handler to drain both queues:

```ts
    if (online && !wasOnline) {
      void replay();
      void replayMedia();
    }
```

Import `replayMedia` from `../offline/mediaQueue` and update the connectivity test's mock to include it.

- [ ] **Step 7: Run the tests and typecheck**

Run: `cd mobile/su-erp-app && npx jest && npx tsc --noEmit`
Expected: every test PASSES, no type errors

- [ ] **Step 8: Commit**

```bash
git add mobile/su-erp-app/src/lib/device/camera.ts mobile/su-erp-app/src/lib/offline/mediaQueue.ts mobile/su-erp-app/src/lib/net/connectivity.ts mobile/su-erp-app/app/\(student\)/grievance.tsx
git commit -m "feat(mobile): add camera evidence capture with deferred upload"
```

---

## Task 8: Canteen pickup token

**Files:**
- Modify: `services/canteen-service/canteen/views.py`, `urls.py`
- Create: `services/canteen-service/canteen/pickup_tokens.py`
- Create: `services/canteen-service/canteen/tests/test_pickup.py`
- Create: `mobile/su-erp-app/app/(student)/pickup.tsx`
- Modify: `mobile/su-erp-app/app/(canteen-owner)/index.tsx`

**Interfaces:**
- Consumes: `sign`/`verify` (Task 1); the order status machine (existing).
- Produces:
  - `GET /api/v1/orders/<uuid:pk>/pickup-token` — student, only when status is `ready`
  - `POST /api/v1/orders/pickup` — canteen-owner, body `{token}`, advances `ready → completed`

- [ ] **Step 1: Write the failing tests**

Create `services/canteen-service/canteen/tests/test_pickup.py`:

```python
"""Pickup tokens: the handoff, not a button, completes an order."""

import uuid

import pytest
from canteen.models import MenuItem, Order, OrderItem

pytestmark = pytest.mark.django_db

TENANT_A = uuid.uuid4()


def _client(tenant_id, role="student", sub="STU-001"):
    from tests.helpers import auth_client  # noqa: PLC0415

    return auth_client(tenant_id=tenant_id, role=role, sub=sub)


def _order(tenant_id, status="ready", student="STU-001"):
    item = MenuItem.objects.create(tenant_id=tenant_id, name="Chai", price="15.00", available=True)
    order = Order.objects.create(
        tenant_id=tenant_id, student_user_code=student, status=status, total="15.00"
    )
    OrderItem.objects.create(
        tenant_id=tenant_id, order=order, menu_item=item, quantity=1, unit_price="15.00"
    )
    return order


def test_a_ready_order_mints_a_pickup_token():
    order = _order(TENANT_A)

    response = _client(TENANT_A).get(f"/api/v1/orders/{order.id}/pickup-token")

    assert response.status_code == 200
    assert response.json()["data"]["token"]


def test_an_order_that_is_not_ready_has_no_token():
    order = _order(TENANT_A, status="preparing")

    response = _client(TENANT_A).get(f"/api/v1/orders/{order.id}/pickup-token")

    assert response.status_code == 400


def test_another_student_cannot_mint_a_token_for_your_order():
    order = _order(TENANT_A, student="STU-001")

    response = _client(TENANT_A, sub="STU-002").get(f"/api/v1/orders/{order.id}/pickup-token")

    assert response.status_code == 403


def test_scanning_a_pickup_token_completes_the_order():
    order = _order(TENANT_A)
    token = _client(TENANT_A).get(f"/api/v1/orders/{order.id}/pickup-token").json()["data"]["token"]

    owner = _client(TENANT_A, role="canteen_owner", sub="OWN-001")
    response = owner.post("/api/v1/orders/pickup", {"token": token}, format="json")

    assert response.status_code == 200
    order.refresh_from_db()
    assert order.status == "completed"


def test_the_same_pickup_token_cannot_complete_twice():
    order = _order(TENANT_A)
    token = _client(TENANT_A).get(f"/api/v1/orders/{order.id}/pickup-token").json()["data"]["token"]
    owner = _client(TENANT_A, role="canteen_owner", sub="OWN-001")
    owner.post("/api/v1/orders/pickup", {"token": token}, format="json")

    response = owner.post("/api/v1/orders/pickup", {"token": token}, format="json")

    assert response.status_code == 400


def test_students_cannot_complete_their_own_order():
    order = _order(TENANT_A)
    token = _client(TENANT_A).get(f"/api/v1/orders/{order.id}/pickup-token").json()["data"]["token"]

    response = _client(TENANT_A).post("/api/v1/orders/pickup", {"token": token}, format="json")

    assert response.status_code == 403
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd services/canteen-service && python -m pytest canteen/tests/test_pickup.py -v`
Expected: FAIL — 404, the routes do not exist

- [ ] **Step 3: Write the token helper**

Create `services/canteen-service/canteen/pickup_tokens.py`:

```python
"""Pickup capability tokens over the shared signer."""

from suerp_common.signed_token import sign, verify

KIND = "pickup"

#: Longer than a bus pass — a student walks up to a counter and waits in a
#: queue, which takes more than thirty seconds.
PICKUP_TTL_SECONDS = 300


def mint(tenant_id, order_id) -> str:
    return sign(
        {"kind": KIND, "tenant_id": str(tenant_id), "order_id": str(order_id)},
        ttl_seconds=PICKUP_TTL_SECONDS,
    )


def read(token: str) -> dict:
    return verify(token, expected_kind=KIND)
```

- [ ] **Step 4: Add the views**

Append to `services/canteen-service/canteen/views.py`:

```python
class PickupTokenView(APIView):
    """GET /api/v1/orders/<id>/pickup-token — the QR the student shows."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            order = Order.objects.get(pk=pk)
        except Order.DoesNotExist:
            return fail("Order not found.", status=404)

        if str(order.student_user_code) != str(request.user.id):
            return fail("This is not your order.", status=403)

        if order.status != Order.Status.READY:
            return fail("This order is not ready for pickup yet.", status=400)

        return ok(
            {"token": pickup_tokens.mint(request.user.tenant_id, order.id),
             "expires_in": pickup_tokens.PICKUP_TTL_SECONDS}
        )


class PickupScanView(APIView):
    """POST /api/v1/orders/pickup — the counter scans and completes.

    Scanning is the only path from ready to completed in the app, which
    means a completed order corresponds to a real handoff rather than a
    stray tap on a busy screen.
    """

    permission_classes = [role_required(*_STAFF_ROLES)]

    def post(self, request):
        token = request.data.get("token", "")
        if not token:
            return fail("A token is required.", status=400)

        try:
            claims = pickup_tokens.read(token)
        except SignedTokenError as exc:
            return fail(f"Invalid pickup token: {exc}", status=400)

        if claims["tenant_id"] != str(request.user.tenant_id):
            return fail("Invalid pickup token: wrong institution.", status=400)

        try:
            order = Order.objects.get(pk=claims["order_id"])
        except Order.DoesNotExist:
            return fail("Order not found.", status=404)

        if order.status != Order.Status.READY:
            return fail(f"Order is '{order.status}', not ready for pickup.", status=400)

        order.status = Order.Status.COMPLETED
        order.save(update_fields=["status", "updated_at"])
        return ok(OrderSerializer(order).data, message="Order handed over.")
```

Add the imports: `from canteen import pickup_tokens`, `from suerp_common.signed_token import SignedTokenError`, `from rest_framework.permissions import IsAuthenticated`.

- [ ] **Step 5: Add the routes**

In `services/canteen-service/canteen/urls.py`:

```python
    path("orders/pickup", PickupScanView.as_view(), name="order-pickup"),
    path("orders/<uuid:pk>/pickup-token", PickupTokenView.as_view(), name="order-pickup-token"),
```

Place `orders/pickup` **before** any `orders/<uuid:pk>` pattern so it is not swallowed by the detail route.

- [ ] **Step 6: Run the tests**

Run: `cd services/canteen-service && python -m pytest canteen/ -v`
Expected: the 6 new tests PASS and every pre-existing canteen test still PASSES

- [ ] **Step 7: Add the app screens**

Create `mobile/su-erp-app/app/(student)/pickup.tsx` — when the student has a `ready` order, render its pickup token as a QR (same `react-native-qrcode-svg` usage as the pass screen), otherwise show the current order status.

In `mobile/su-erp-app/app/(canteen-owner)/index.tsx`, replace the "Mark completed" button on `ready` orders with a "Scan pickup" action that opens the `CameraView` scanner (same shape as `app/(driver)/scan.tsx`) and posts to `/api/v1/orders/pickup`. Leave `placed → preparing → ready` as ordinary buttons.

- [ ] **Step 8: Typecheck and commit**

Run: `cd mobile/su-erp-app && npx tsc --noEmit && npx jest`

```bash
git add services/canteen-service/ mobile/su-erp-app/app/
git commit -m "feat(canteen): complete orders by scanning a pickup token"
```

---

## Task 9: Push notifications

**Files:**
- Create: `services/notification-service/notify/push.py`
- Modify: `services/notification-service/notify/consumers.py`, `models.py`
- Create: `services/notification-service/notify/tests/test_push.py`
- Create: `mobile/su-erp-app/src/lib/push/register.ts`
- Modify: `mobile/su-erp-app/src/lib/auth/session.ts`

**Interfaces:**
- Produces:
  - `class PushChannel(Protocol)` with `send(tokens: list[str], title: str, body: str, data: dict) -> list[str]` returning stale tokens
  - `ExpoPushChannel` implementing it
  - `get_channel() -> PushChannel` — swappable via settings
  - The existing notification consumer additionally pushes
  - `registerPushToken(): Promise<void>` in the app, called after login

- [ ] **Step 1: Read the existing consumer**

Run: `cat services/notification-service/notify/consumers.py`
Record how it creates `Notification` rows for `payment.success`, `allocation.confirmed`, and `grievance.scored`. The push send hooks into the same place, after the row is created.

- [ ] **Step 2: Write the failing tests**

Create `services/notification-service/notify/tests/test_push.py`:

```python
"""Push delivery alongside the in-app inbox."""

import uuid
from unittest.mock import patch

import pytest
from notify.models import Notification
from notify.push import ExpoPushChannel

pytestmark = pytest.mark.django_db

TENANT_A = uuid.uuid4()


def test_the_channel_posts_to_expo_and_returns_stale_tokens():
    channel = ExpoPushChannel()

    with patch("notify.push.requests.post") as post:
        post.return_value.json.return_value = {
            "data": [
                {"status": "ok"},
                {"status": "error", "details": {"error": "DeviceNotRegistered"}},
            ]
        }
        post.return_value.raise_for_status.return_value = None

        stale = channel.send(["tok-good", "tok-dead"], "Hi", "Body", {"path": "/fees"})

    assert stale == ["tok-dead"]


def test_a_transport_failure_does_not_raise():
    """A push outage must never take down the consumer — the inbox row is
    the source of truth and has already been written."""
    channel = ExpoPushChannel()

    with patch("notify.push.requests.post", side_effect=Exception("network down")):
        stale = channel.send(["tok"], "Hi", "Body", {})

    assert stale == []


def test_the_consumer_still_writes_an_inbox_row_when_push_fails():
    from notify.consumers import handle_event  # noqa: PLC0415

    with patch("notify.push.get_channel") as get_channel:
        get_channel.return_value.send.side_effect = Exception("push down")
        handle_event(
            {
                "event_type": "payment.success",
                "tenant_id": str(TENANT_A),
                "payload": {"student_user_code": "STU-001", "amount": "1500.00"},
            }
        )

    assert Notification.objects.filter(user_code="STU-001").exists()
```

Adjust `handle_event`'s name and signature to match what `consumers.py` actually exposes — read it in Step 1 and use the real entry point.

- [ ] **Step 3: Run them to verify they fail**

Run: `cd services/notification-service && python -m pytest notify/tests/test_push.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'notify.push'`

- [ ] **Step 4: Write the push channel**

Create `services/notification-service/notify/push.py`:

```python
"""Push delivery, behind an interface.

Expo today; FCM later without touching the consumer. Expo is the choice
because it removes the entire APNs-certificate and google-services.json
burden, which is real setup cost for a capability the platform needs to
demonstrate, not to operate at scale.

Delivery is best-effort by design: the in-app inbox row is the source of
truth and is written first. A push outage must never fail an event consumer,
because that would make a notification failure look like a payment failure.
"""

import logging
from typing import Protocol

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
PUSH_TIMEOUT_SECONDS = 5


class PushChannel(Protocol):
    def send(self, tokens: list[str], title: str, body: str, data: dict) -> list[str]:
        """Deliver to each token. Returns tokens the provider says are dead."""
        ...


class ExpoPushChannel:
    def send(self, tokens: list[str], title: str, body: str, data: dict) -> list[str]:
        if not tokens:
            return []

        messages = [
            {"to": token, "title": title, "body": body, "data": data} for token in tokens
        ]

        try:
            response = requests.post(
                EXPO_PUSH_URL, json=messages, timeout=PUSH_TIMEOUT_SECONDS
            )
            response.raise_for_status()
            receipts = response.json().get("data", [])
        except Exception:
            logger.exception("Push delivery failed; inbox rows are unaffected.")
            return []

        stale = []
        for token, receipt in zip(tokens, receipts, strict=False):
            details = receipt.get("details") or {}
            if receipt.get("status") == "error" and details.get("error") == "DeviceNotRegistered":
                stale.append(token)
        return stale


class NullPushChannel:
    """Used in tests and local runs — accepts everything, sends nothing."""

    def send(self, tokens: list[str], title: str, body: str, data: dict) -> list[str]:
        return []


def get_channel() -> PushChannel:
    if getattr(settings, "PUSH_ENABLED", False):
        return ExpoPushChannel()
    return NullPushChannel()
```

- [ ] **Step 5: Add a device-token table and hook the consumer**

`notification-service` has its own database and cannot read auth-service's `Device` table. Add a local projection:

```python
class PushDevice(TenantModel):
    """Push tokens, projected into this service.

    auth-service owns the authoritative Device row; this is a local copy
    populated by the app registering its token here after login, because
    DB-per-service means this service cannot join across to it.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_code = models.CharField(max_length=30)
    push_token = models.CharField(max_length=255, unique=True)
    is_stale = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
```

Add `POST /api/v1/notify/devices` (authenticated) that upserts the caller's token, and in the consumer — **after** the `Notification` row is committed — look up that user's live tokens and call `get_channel().send(...)`, marking any returned tokens stale. Wrap the push call in its own `try/except` so it can never abort the consumer.

- [ ] **Step 6: Write the app registration**

Run: `cd mobile/su-erp-app && npx expo install expo-notifications expo-device`

Create `mobile/su-erp-app/src/lib/push/register.ts`:

```ts
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';

import { request } from '@/lib/api/client';

/**
 * Registers this device for push. Called after login, when there is a
 * session to attach the token to. Failure is non-fatal — the in-app inbox
 * still works, so a denied permission must not block sign-in.
 */
export async function registerPushToken(): Promise<void> {
  if (!Device.isDevice) return;

  const existing = await Notifications.getPermissionsAsync();
  const status =
    existing.status === 'granted'
      ? existing.status
      : (await Notifications.requestPermissionsAsync()).status;

  if (status !== 'granted') return;

  const token = (await Notifications.getExpoPushTokenAsync()).data;

  try {
    await request('/api/v1/notify/devices', {
      method: 'POST',
      body: JSON.stringify({ push_token: token }),
    });
  } catch {
    // Non-fatal: the inbox is the source of truth.
  }
}
```

Call it from `useSession.signIn` after `fetchMe()` resolves, and add a `Notifications.addNotificationResponseReceivedListener` in `app/_layout.tsx` that routes to the `path` carried in the push payload.

- [ ] **Step 7: Migrate, test, and commit**

Run:
```bash
cd services/notification-service && python manage.py makemigrations notify && python -m pytest notify/ -v
cd ../../mobile/su-erp-app && npx tsc --noEmit
```
Expected: all notify tests PASS, no type errors

```bash
git add services/notification-service/ mobile/su-erp-app/src/lib/push/ mobile/su-erp-app/src/lib/auth/session.ts mobile/su-erp-app/app/_layout.tsx
git commit -m "feat(notify): add Expo push channel behind a swappable interface"
```

---

## Task 10: Live bus map, widgets, and document vault

**Files:**
- Create: `mobile/su-erp-app/src/features/bustrack/useLiveBus.ts`
- Modify: `mobile/su-erp-app/app/(student)/transport.tsx`
- Create: `mobile/su-erp-app/src/features/vault/useVault.ts`
- Create: `mobile/su-erp-app/app/(student)/vault.tsx`
- Create: `mobile/su-erp-app/widgets/` (platform widget targets)

**Interfaces:**
- Consumes: `GET /api/v1/transport/routes/<id>/live` (Phase 3 Task 2); receipt PDF endpoints (existing in finance-service).
- Produces:
  - `useLiveBus(routeId)` — polls the live position every 15s while the screen is focused
  - `downloadDocument(url, name): Promise<string>` and `listVault(): Promise<VaultEntry[]>`
  - Home-screen widget showing next class, bus ETA, and order status

- [ ] **Step 1: Add the live-bus hook**

Create `mobile/su-erp-app/src/features/bustrack/useLiveBus.ts`:

```ts
import type { LivePosition } from '@api-types/index';
import { useQuery } from '@tanstack/react-query';

import { request } from '@/lib/api/client';

export const liveBusKey = (routeId: string) => ['transport', 'live', routeId];

export function useLiveBus(routeId: string | null) {
  return useQuery({
    queryKey: liveBusKey(routeId ?? ''),
    queryFn: () => request<LivePosition>(`/api/v1/transport/routes/${routeId}/live`),
    enabled: Boolean(routeId),
    // The server's own key expires after 60s, so polling faster than the
    // driver's 15s broadcast interval would only return the same point.
    refetchInterval: 15_000,
    // A 404 means no bus is running — not an error worth retrying.
    retry: false,
  });
}
```

- [ ] **Step 2: Render the bus on the transport screen**

Run: `cd mobile/su-erp-app && npx expo install react-native-maps`

In `app/(student)/transport.tsx`, add a `MapView` above the schedule list when a route is selected. Place a marker at the `useLiveBus(routeId)` position. When the query 404s, render "No bus running on this route right now" in place of the map rather than an empty grey rectangle.

- [ ] **Step 3: Build the document vault**

Run: `cd mobile/su-erp-app && npx expo install expo-sharing`

Create `mobile/su-erp-app/src/features/vault/useVault.ts` with:
- `downloadDocument(url, name)` — `FileSystem.downloadAsync` into `FileSystem.documentDirectory + 'vault/'`, returning the local URI
- `listVault()` — `FileSystem.readDirectoryAsync` over that folder
- `shareDocument(uri)` — `Sharing.shareAsync(uri)`

Create `app/(student)/vault.tsx` listing downloaded receipts and hall tickets with a download button per invoice (using the existing `/api/v1/finance/receipts/by-invoice/<id>/pdf` endpoint) and a share action per stored file. The list must render with no network — that is the entire point of the feature, so read the directory rather than the API.

- [ ] **Step 4: Add the widgets**

Run: `cd mobile/su-erp-app && npm install @bacons/apple-targets`

Create an iOS widget target rendering next class, bus ETA, and order status from a shared app-group store, and an Android widget provider reading the same values from a `SharedPreferences` bridge. Write those three values into the shared store whenever the home screen query resolves, so the widget never makes its own API call.

Add a Live Activity for an in-flight canteen order, started when an order reaches `placed` and ended when it reaches `completed`.

**Note:** widgets require a dev-build and cannot be tested in Expo Go. If the EAS build queue makes this impractical within the phase, ship Tasks 1–9 and treat widgets as a follow-up — they are the one feature here with no backend dependency, so deferring them blocks nothing.

- [ ] **Step 5: Register the new tabs**

Add `vault` to `app/(student)/_layout.tsx`.

- [ ] **Step 6: Typecheck, test, and commit**

Run: `cd mobile/su-erp-app && npx jest && npx tsc --noEmit`

```bash
git add mobile/su-erp-app/
git commit -m "feat(mobile): add live bus map, document vault, and home-screen widgets"
```

---

## Task 11: End-to-end verification

**Files:**
- Modify: `docs/RUNBOOK-mobile.md`
- Modify: `README.md`

- [ ] **Step 1: Run every backend suite**

Run:
```bash
for s in shared/libs/suerp_common services/transport-service services/attendance-service \
         services/grievance-service services/canteen-service services/notification-service; do
  echo "== $s"; (cd "$s" && python -m pytest -q) || echo "FAILED: $s";
done
```
Expected: every suite passes. Record any failure verbatim rather than moving on.

- [ ] **Step 2: Verify each hardware feature on a real device**

A physical device is required — an emulator cannot exercise the camera, GPS, or biometrics honestly.

- **QR pass:** open the pass screen, confirm the code visibly re-renders within 30 seconds, scan it from the driver's device, confirm acceptance, then scan the same screenshot again and confirm a 409.
- **Attendance:** open a session from the web dashboard, mark from inside the room, then walk outside the radius and confirm refusal.
- **Live bus:** start a driver trip, confirm the student map marker moves.
- **Camera grievance:** attach a photo, resolve the ticket, then run `purge_expired_media_task` manually with `expires_at` backdated and confirm the log shows "purged" with the file gone.
- **Pickup token:** advance an order to ready, scan from the owner device, confirm completion.
- **Push:** trigger a payment and confirm the phone buzzes with a deep link that opens the fees screen.
- **Vault:** download a receipt, enable airplane mode, confirm it still opens and shares.

- [ ] **Step 3: Record the results**

Append a "Phase 4 — hardware features" section to `docs/RUNBOOK-mobile.md` covering each check above with its observed outcome, and note explicitly whether widgets shipped or were deferred.

- [ ] **Step 4: Update the README**

Add a "Mobile app" section to `README.md` describing the four roles, the eight hardware-only features, and the offline model, with a pointer to the spec and the four phase plans.

- [ ] **Step 5: Commit**

```bash
git add docs/RUNBOOK-mobile.md README.md
git commit -m "docs: record verified hardware features and document the mobile app"
```

---

## Known gaps after Phase 4

Recorded honestly rather than left implied:

- **Symmetric scan key.** `/scan-key` hands the shared HS256 secret to scanner devices, so a compromised driver phone can mint passes. Moving to asymmetric signing (server holds the private key, scanners hold only the public key) removes this and is the right next security task.
- **BLE proximity attendance.** Deferred — needs a room beacon since faculty has no app. Geofence plus rolling code is the shipped defense.
- **Queued attendance marks expire.** A mark queued longer than ~30 seconds carries a stale code and is refused on replay. Deliberate: accepting old codes would reopen the proxy hole.
- **Widgets require a dev-build.** Not testable in Expo Go, and possibly deferred (Task 10 Step 4).
- **Push is best-effort.** No delivery receipts beyond stale-token pruning, and no retry — the in-app inbox remains the source of truth.
