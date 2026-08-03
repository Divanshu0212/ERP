# Mobile Phase 1 — Auth Hardening & App Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden `auth-service` for mobile clients (refresh-token rotation with reuse detection, device sessions, logout) and scaffold a React Native app that logs in, routes by role, survives offline, and queues writes.

**Architecture:** The app calls the existing Nginx gateway at `/api/v1/*` with the same HS256 JWT the web app uses — no BFF. Backend gains two tenant-scoped models (`RefreshToken`, `Device`) that turn the currently stateless refresh into a tracked, revocable chain. The app is layered: `lib/api` (HTTP only) → `lib/offline` (SQLite queue) → `lib/device` (hardware behind interfaces) → `features/*` (screens). Nothing above `lib/api` knows about HTTP; nothing below `features` knows about React.

**Tech Stack:** Django 5 + DRF + `djangorestframework-simplejwt` (backend); Expo dev-build + TypeScript + Expo Router + TanStack Query + MMKV + Zustand + NativeWind + `expo-sqlite` + `expo-secure-store` (app).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-02-mobile-app-design.md`. Branch: `feat/mobile-app`.
- Access token lifetime **15 minutes**; refresh token lifetime **30 days** (spec §3.4). `config/settings.py:188` currently says `timedelta(days=7)` — Task 3 changes it.
- Access token lives in **memory only**, never written to disk. Refresh token lives in `expo-secure-store` only. MMKV and SQLite hold cached data, never credentials.
- JWT claim keys are exactly `sub` (= `user.user_code`), `role`, `tenant` (= `str(user.tenant_id)`). Every service reads this shape via `suerp_common.auth.JWTAuthentication`. Do not rename or add required claims.
- All API responses use the envelope from `shared/libs/suerp_common/suerp_common/envelope.py`: `{"success", "data", "message", "errors"}`. Use `ok()` / `fail()`, never bare `Response`.
- `User.user_code` is the primary key (a string), not a UUID. `Institution.id` is a UUID. Tenant scoping in auth-service is an explicit `tenant` ForeignKey, **not** `TenantModel` — see the `accounts/models.py` module docstring for why.
- Every new model gets a `tenant` FK to `Institution` and every query filters on it explicitly.
- Backend tests: `pytest` from inside `services/auth-service`, file naming `test_*.py` under `accounts/tests/`, `pytestmark = pytest.mark.django_db`.
- App package name: `su-erp-app`, at `mobile/su-erp-app/`. Do not touch `frontend/su-erp-web/`.
- Commit as `Divanshu0212 <divanshubhargava026@gmail.com>`, no co-author trailer. Commit after every task.

---

## File Structure

**Backend — `services/auth-service/`**

| File | Responsibility |
| --- | --- |
| `accounts/models.py` (modify) | add `Device` and `RefreshToken` models |
| `accounts/token_service.py` (create) | mint / rotate / revoke refresh chains. Pure functions, no HTTP. |
| `accounts/serializers.py` (modify) | `DeviceSerializer`, extend `LoginSerializer` and `RefreshSerializer` with device fields |
| `accounts/views.py` (modify) | rewrite `RefreshView`, extend `LoginView`, add `LogoutView`, `DeviceListView`, `DeviceRevokeView` |
| `accounts/urls.py` (modify) | wire the three new routes |
| `accounts/tests/test_token_rotation.py` (create) | rotation, reuse detection, expiry |
| `accounts/tests/test_devices.py` (create) | device binding, list, revoke, cross-tenant isolation |

**App — `mobile/su-erp-app/`**

| File | Responsibility |
| --- | --- |
| `app/_layout.tsx` | root providers (Query, Zustand hydration, offline banner) |
| `app/index.tsx` | boot gate: route to login or the role shell |
| `app/(auth)/login.tsx` | login form |
| `app/(student)/_layout.tsx`, `(warden)/`, `(driver)/`, `(canteen-owner)/` | per-role tab shells |
| `src/lib/api/client.ts` | `apiClient` — base URL, bearer, `X-Request-Id`, 401 refresh-retry |
| `src/lib/api/auth.ts` | `login`, `refresh`, `logout`, `me`, `listDevices`, `revokeDevice` |
| `src/lib/auth/session.ts` | Zustand store: tokens, user, role |
| `src/lib/auth/storage.ts` | SecureStore read/write for refresh token + device id |
| `src/lib/offline/queue.ts` | SQLite mutation queue: enqueue, list, replay, drop |
| `src/lib/offline/replay.ts` | connectivity listener driving `queue.replay()` |
| `src/lib/device/identity.ts` | stable `device_id` generation and retrieval |
| `src/lib/device/biometrics.ts` | `Biometrics` interface + real implementation |
| `shared/api-types/auth.ts` (repo root `shared/`) | request/response types shared by web and app |

---

## Task 1: `Device` model

**Files:**
- Modify: `services/auth-service/accounts/models.py`
- Create: `services/auth-service/accounts/tests/test_devices.py`
- Create (generated): `services/auth-service/accounts/migrations/000X_device.py`

**Interfaces:**
- Consumes: `Institution`, `User` from `accounts.models`.
- Produces: `Device` model with fields `id: UUID`, `device_id: str`, `tenant: FK[Institution]`, `user: FK[User]`, `platform: str`, `model_name: str`, `push_token: str`, `last_seen_at: datetime`, `is_stale: bool`, `created_at: datetime`. Unique constraint on `(user, device_id)`.

- [ ] **Step 1: Write the failing test**

Create `services/auth-service/accounts/tests/test_devices.py`:

```python
"""Device model: per-user device registry backing mobile refresh chains and push."""

import pytest
from accounts.models import Device, Institution, User
from django.db import IntegrityError

pytestmark = pytest.mark.django_db


def _institution(slug="alpha"):
    return Institution.objects.create(slug=slug, name=f"{slug} University")


def _user(institution, email="student@example.com", user_code="STU-001"):
    return User.objects.create_user(
        tenant=institution,
        email=email,
        password="s3cur3-passw0rd",
        user_code=user_code,
        role=User.Role.STUDENT,
    )


def test_device_registers_for_a_user():
    inst = _institution()
    user = _user(inst)

    device = Device.objects.create(
        tenant=inst,
        user=user,
        device_id="11111111-1111-4111-8111-111111111111",
        platform="android",
        model_name="Pixel 7",
    )

    assert device.is_stale is False
    assert device.push_token == ""
    assert device.tenant_id == inst.id


def test_same_device_id_cannot_register_twice_for_one_user():
    inst = _institution()
    user = _user(inst)
    Device.objects.create(
        tenant=inst, user=user, device_id="dev-1", platform="ios", model_name="iPhone 14"
    )

    with pytest.raises(IntegrityError):
        Device.objects.create(
            tenant=inst, user=user, device_id="dev-1", platform="ios", model_name="iPhone 14"
        )


def test_same_device_id_may_exist_for_different_users():
    inst = _institution()
    alice = _user(inst, email="alice@example.com", user_code="STU-001")
    bob = _user(inst, email="bob@example.com", user_code="STU-002")

    Device.objects.create(
        tenant=inst, user=alice, device_id="shared", platform="android", model_name="A"
    )
    Device.objects.create(
        tenant=inst, user=bob, device_id="shared", platform="android", model_name="A"
    )

    assert Device.objects.filter(device_id="shared").count() == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd services/auth-service && python -m pytest accounts/tests/test_devices.py -v`
Expected: FAIL — `ImportError: cannot import name 'Device' from 'accounts.models'`

- [ ] **Step 3: Add the model**

Append to `services/auth-service/accounts/models.py`:

```python
class Device(models.Model):
    """A mobile device bound to one user.

    The app generates ``device_id`` once and keeps it in SecureStore, so it
    survives reinstall-free relaunches and identifies the same physical
    device across logins. Refresh-token chains are bound to a device
    (see ``RefreshToken.device``), which is what makes per-device revocation
    possible. This table doubles as the push-token registry — one row per
    device serves both concerns.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Institution, on_delete=models.PROTECT, related_name="devices")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="devices")
    device_id = models.CharField(max_length=64)
    platform = models.CharField(max_length=16)
    model_name = models.CharField(max_length=128, blank=True, default="")
    push_token = models.CharField(max_length=255, blank=True, default="")
    is_stale = models.BooleanField(default=False)
    last_seen_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "device_id"], name="unique_device_per_user"),
        ]
        indexes = [
            models.Index(fields=["tenant", "user"], name="device_tenant_user"),
        ]

    def __str__(self):
        return f"{self.platform}:{self.device_id} ({self.user_id})"
```

- [ ] **Step 4: Generate and run the migration**

Run: `cd services/auth-service && python manage.py makemigrations accounts && python -m pytest accounts/tests/test_devices.py -v`
Expected: migration created; all 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add services/auth-service/accounts/models.py services/auth-service/accounts/migrations/ services/auth-service/accounts/tests/test_devices.py
git commit -m "feat(auth): add Device model for mobile session and push registry"
```

---

## Task 2: `RefreshToken` model

**Files:**
- Modify: `services/auth-service/accounts/models.py`
- Create: `services/auth-service/accounts/tests/test_token_rotation.py`
- Create (generated): `services/auth-service/accounts/migrations/000X_refreshtoken.py`

**Interfaces:**
- Consumes: `Institution`, `User`, `Device` from Task 1.
- Produces: `RefreshTokenRecord` model — named with a `Record` suffix because `rest_framework_simplejwt.tokens.RefreshToken` is already imported under the bare name in `accounts/views.py`. Fields: `jti: str (unique)`, `tenant: FK`, `user: FK`, `device: FK[Device]`, `expires_at: datetime`, `revoked_at: datetime|None`, `replaced_by: FK[self]|None`, `created_at`. Property `is_live: bool`.

- [ ] **Step 1: Write the failing test**

Create `services/auth-service/accounts/tests/test_token_rotation.py`:

```python
"""RefreshTokenRecord: the persisted rotation chain behind mobile refresh."""

import pytest
from accounts.models import Device, Institution, RefreshTokenRecord, User
from django.utils import timezone

pytestmark = pytest.mark.django_db


def _institution(slug="alpha"):
    return Institution.objects.create(slug=slug, name=f"{slug} University")


def _user(institution, email="student@example.com", user_code="STU-001"):
    return User.objects.create_user(
        tenant=institution,
        email=email,
        password="s3cur3-passw0rd",
        user_code=user_code,
        role=User.Role.STUDENT,
    )


def _device(institution, user, device_id="dev-1"):
    return Device.objects.create(
        tenant=institution,
        user=user,
        device_id=device_id,
        platform="android",
        model_name="Pixel 7",
    )


def test_new_record_is_live():
    inst = _institution()
    user = _user(inst)
    record = RefreshTokenRecord.objects.create(
        tenant=inst,
        user=user,
        device=_device(inst, user),
        jti="jti-1",
        expires_at=timezone.now() + timezone.timedelta(days=30),
    )

    assert record.is_live is True


def test_revoked_record_is_not_live():
    inst = _institution()
    user = _user(inst)
    record = RefreshTokenRecord.objects.create(
        tenant=inst,
        user=user,
        device=_device(inst, user),
        jti="jti-2",
        expires_at=timezone.now() + timezone.timedelta(days=30),
        revoked_at=timezone.now(),
    )

    assert record.is_live is False


def test_expired_record_is_not_live():
    inst = _institution()
    user = _user(inst)
    record = RefreshTokenRecord.objects.create(
        tenant=inst,
        user=user,
        device=_device(inst, user),
        jti="jti-3",
        expires_at=timezone.now() - timezone.timedelta(seconds=1),
    )

    assert record.is_live is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd services/auth-service && python -m pytest accounts/tests/test_token_rotation.py -v`
Expected: FAIL — `ImportError: cannot import name 'RefreshTokenRecord'`

- [ ] **Step 3: Add the model**

Append to `services/auth-service/accounts/models.py`:

```python
class RefreshTokenRecord(models.Model):
    """One issued refresh token, tracked so it can be rotated and revoked.

    SimpleJWT's refresh tokens are stateless by default: anyone holding a
    signed token can refresh forever and there is no logout. A mobile client
    needs both. Persisting one row per issued token turns the chain into
    something the server controls — ``replaced_by`` links each token to its
    successor, so presenting an already-rotated token proves the token was
    captured, and the whole chain can be revoked in response.

    Named ``RefreshTokenRecord`` rather than ``RefreshToken`` because
    ``accounts/views.py`` already imports SimpleJWT's ``RefreshToken`` class.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Institution, on_delete=models.PROTECT, related_name="refresh_tokens")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="refresh_tokens")
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="refresh_tokens")
    jti = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    replaced_by = models.OneToOneField(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="replaces"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "device"], name="refresh_user_device"),
        ]

    @property
    def is_live(self) -> bool:
        """Usable right now: neither revoked nor past its expiry."""
        from django.utils import timezone as _tz

        return self.revoked_at is None and self.expires_at > _tz.now()

    def __str__(self):
        return f"{self.jti} ({'live' if self.is_live else 'dead'})"
```

- [ ] **Step 4: Generate the migration and run the tests**

Run: `cd services/auth-service && python manage.py makemigrations accounts && python -m pytest accounts/tests/test_token_rotation.py -v`
Expected: all 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add services/auth-service/accounts/models.py services/auth-service/accounts/migrations/ services/auth-service/accounts/tests/test_token_rotation.py
git commit -m "feat(auth): add RefreshTokenRecord model for rotation chains"
```

---

## Task 3: Token service — issue, rotate, revoke

**Files:**
- Create: `services/auth-service/accounts/token_service.py`
- Modify: `services/auth-service/config/settings.py:188` (refresh lifetime 7 → 30 days)
- Modify: `services/auth-service/accounts/tests/test_token_rotation.py` (append)

**Interfaces:**
- Consumes: `Device`, `RefreshTokenRecord` (Tasks 1–2); `_issue_tokens` claim shape from `accounts/views.py:45`.
- Produces:
  - `register_device(user, device_id: str, platform: str, model_name: str, push_token: str = "") -> Device`
  - `issue_for_device(user, device: Device) -> dict` returning `{"access": str, "refresh": str}`
  - `rotate(raw_refresh: str) -> dict` returning `{"access": str, "refresh": str}`; raises `TokenReuseError` or `TokenInvalidError`
  - `revoke_device_chain(device: Device) -> int` returning the number of records revoked
  - exceptions `TokenInvalidError`, `TokenReuseError` (both subclass `Exception`)

- [ ] **Step 1: Write the failing tests**

Append to `services/auth-service/accounts/tests/test_token_rotation.py`:

```python
from accounts.token_service import (
    TokenReuseError,
    issue_for_device,
    register_device,
    revoke_device_chain,
    rotate,
)


def test_issue_then_rotate_returns_a_new_refresh_and_revokes_the_old():
    inst = _institution()
    user = _user(inst)
    device = register_device(user, "dev-1", "android", "Pixel 7")

    first = issue_for_device(user, device)
    second = rotate(first["refresh"])

    assert second["refresh"] != first["refresh"]
    assert RefreshTokenRecord.objects.count() == 2

    old = RefreshTokenRecord.objects.get(replaced_by__isnull=False)
    assert old.revoked_at is not None
    assert old.is_live is False
    assert old.replaced_by.is_live is True


def test_rotated_access_token_carries_sub_role_tenant_claims():
    import jwt
    from django.conf import settings

    inst = _institution()
    user = _user(inst)
    device = register_device(user, "dev-1", "android", "Pixel 7")

    tokens = rotate(issue_for_device(user, device)["refresh"])
    claims = jwt.decode(
        tokens["access"], settings.SIMPLE_JWT["SIGNING_KEY"], algorithms=["HS256"]
    )

    assert claims["sub"] == user.user_code
    assert claims["role"] == user.role
    assert claims["tenant"] == str(user.tenant_id)


def test_reusing_an_already_rotated_token_revokes_the_whole_chain():
    inst = _institution()
    user = _user(inst)
    device = register_device(user, "dev-1", "android", "Pixel 7")

    first = issue_for_device(user, device)
    rotate(first["refresh"])

    with pytest.raises(TokenReuseError):
        rotate(first["refresh"])

    assert RefreshTokenRecord.objects.filter(revoked_at__isnull=True).count() == 0


def test_revoke_device_chain_kills_every_live_record_for_that_device_only():
    inst = _institution()
    user = _user(inst)
    phone = register_device(user, "dev-phone", "android", "Pixel 7")
    tablet = register_device(user, "dev-tablet", "android", "Tab S9")
    issue_for_device(user, phone)
    tablet_tokens = issue_for_device(user, tablet)

    revoked = revoke_device_chain(phone)

    assert revoked == 1
    assert RefreshTokenRecord.objects.get(device=tablet).is_live is True
    # the surviving device's token still rotates
    assert rotate(tablet_tokens["refresh"])["access"]


def test_register_device_is_idempotent_for_the_same_device_id():
    inst = _institution()
    user = _user(inst)

    first = register_device(user, "dev-1", "android", "Pixel 7")
    second = register_device(user, "dev-1", "android", "Pixel 7 Pro")

    assert first.id == second.id
    assert second.model_name == "Pixel 7 Pro"
    assert Device.objects.filter(user=user).count() == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd services/auth-service && python -m pytest accounts/tests/test_token_rotation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'accounts.token_service'`

- [ ] **Step 3: Set the refresh lifetime to 30 days**

In `services/auth-service/config/settings.py`, change line 188:

```python
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
```

- [ ] **Step 4: Write the token service**

Create `services/auth-service/accounts/token_service.py`:

```python
"""Issue, rotate, and revoke device-bound refresh chains.

Pure functions over the models — no HTTP, no DRF. ``accounts/views.py`` is
the only caller. Keeping the chain logic here means the reuse-detection
rule lives in exactly one place and can be tested without a request.

The claim shape (``sub``/``role``/``tenant``) mirrors ``views._issue_tokens``
because every other service reads exactly those keys via
``suerp_common.auth.JWTAuthentication``.
"""

from datetime import datetime, timezone as dt_timezone

from accounts.models import Device, RefreshTokenRecord, User
from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken


class TokenInvalidError(Exception):
    """The presented refresh token is malformed, expired, or unknown."""


class TokenReuseError(Exception):
    """A refresh token that was already rotated was presented again.

    Treated as theft: the entire device chain is revoked before raising.
    """


def _stamp_claims(token, user: User) -> None:
    token["sub"] = user.user_code
    token["role"] = user.role
    token["tenant"] = str(user.tenant_id)


def register_device(
    user: User,
    device_id: str,
    platform: str,
    model_name: str = "",
    push_token: str = "",
) -> Device:
    """Create or refresh the caller's device row. Idempotent per device_id."""
    device, created = Device.objects.get_or_create(
        user=user,
        device_id=device_id,
        defaults={
            "tenant_id": user.tenant_id,
            "platform": platform,
            "model_name": model_name,
            "push_token": push_token,
        },
    )
    if not created:
        device.platform = platform
        device.model_name = model_name
        if push_token:
            device.push_token = push_token
        device.is_stale = False
        device.save(update_fields=["platform", "model_name", "push_token", "is_stale"])
    return device


def issue_for_device(user: User, device: Device) -> dict:
    """Mint a fresh access+refresh pair and record the refresh token."""
    refresh = RefreshToken.for_user(user)
    _stamp_claims(refresh, user)

    access = refresh.access_token
    _stamp_claims(access, user)

    RefreshTokenRecord.objects.create(
        tenant_id=user.tenant_id,
        user=user,
        device=device,
        jti=refresh["jti"],
        expires_at=datetime.fromtimestamp(refresh["exp"], tz=dt_timezone.utc),
    )

    return {"access": str(access), "refresh": str(refresh)}


def _revoke(records) -> int:
    return records.update(revoked_at=timezone.now())


def revoke_device_chain(device: Device) -> int:
    """Revoke every live refresh token issued to this device."""
    return _revoke(RefreshTokenRecord.objects.filter(device=device, revoked_at__isnull=True))


@transaction.atomic
def rotate(raw_refresh: str) -> dict:
    """Exchange a refresh token for a new pair, revoking the presented one.

    Presenting a token that was already rotated (``replaced_by`` is set) means
    two parties hold the same token — the legitimate client and whoever
    captured it. There is no way to tell which is which, so the whole device
    chain dies and both are forced to re-authenticate.
    """
    try:
        token = RefreshToken(raw_refresh)
    except TokenError as exc:
        raise TokenInvalidError(str(exc)) from exc

    try:
        record = RefreshTokenRecord.objects.select_for_update().get(jti=token["jti"])
    except RefreshTokenRecord.DoesNotExist as exc:
        raise TokenInvalidError("Unknown refresh token.") from exc

    if record.replaced_by_id is not None:
        revoke_device_chain(record.device)
        raise TokenReuseError("Refresh token was already used; device chain revoked.")

    if not record.is_live:
        raise TokenInvalidError("Refresh token is revoked or expired.")

    user = record.user
    if not user.is_active:
        raise TokenInvalidError("User is inactive.")

    tokens = issue_for_device(user, record.device)

    successor = RefreshTokenRecord.objects.get(jti=RefreshToken(tokens["refresh"])["jti"])
    record.revoked_at = timezone.now()
    record.replaced_by = successor
    record.save(update_fields=["revoked_at", "replaced_by"])

    return tokens
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd services/auth-service && python -m pytest accounts/tests/test_token_rotation.py -v`
Expected: all 8 tests PASS

- [ ] **Step 6: Commit**

```bash
git add services/auth-service/accounts/token_service.py services/auth-service/accounts/tests/test_token_rotation.py services/auth-service/config/settings.py
git commit -m "feat(auth): add token service with rotation and reuse detection"
```

---

## Task 4: Wire login, refresh, and logout to the chain

**Files:**
- Modify: `services/auth-service/accounts/views.py:98-179` (`LoginView`, `RefreshView`), add `LogoutView`
- Modify: `services/auth-service/accounts/serializers.py` (extend `LoginSerializer`, `RefreshSerializer`)
- Modify: `services/auth-service/accounts/urls.py`
- Create: `services/auth-service/accounts/tests/test_mobile_auth_flow.py`

**Interfaces:**
- Consumes: `register_device`, `issue_for_device`, `rotate`, `revoke_device_chain`, `TokenInvalidError`, `TokenReuseError` from Task 3.
- Produces: `POST /api/v1/auth/login` accepting optional `device_id`/`platform`/`model_name`/`push_token`; `POST /api/v1/auth/refresh` returning `{"access", "refresh"}`; `POST /api/v1/auth/logout` accepting `{"refresh"}` and returning 200.

**Backward compatibility:** the web app posts login without device fields and refresh without a tracked token. When `device_id` is absent, `LoginView` keeps its current stateless `_issue_tokens` path, and `RefreshView` falls back to the old stateless branch when the presented token has no `RefreshTokenRecord`. Web behavior must not change.

- [ ] **Step 1: Write the failing tests**

Create `services/auth-service/accounts/tests/test_mobile_auth_flow.py`:

```python
"""Mobile login/refresh/logout over device-bound rotation chains.

The web app's stateless flow must keep working unchanged — see the
backward-compatibility tests at the bottom.
"""

import pytest
from accounts.models import Device, Institution, RefreshTokenRecord, User
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

PASSWORD = "s3cur3-passw0rd"


@pytest.fixture
def client():
    return APIClient()


def _institution(slug="alpha"):
    return Institution.objects.create(slug=slug, name=f"{slug} University")


def _user(institution, email="student@example.com", user_code="STU-001"):
    return User.objects.create_user(
        tenant=institution,
        email=email,
        password=PASSWORD,
        user_code=user_code,
        role=User.Role.STUDENT,
    )


def _login(client, institution, device_id="dev-1", email="student@example.com"):
    payload = {"institution_slug": institution.slug, "email": email, "password": PASSWORD}
    if device_id is not None:
        payload |= {"device_id": device_id, "platform": "android", "model_name": "Pixel 7"}
    return client.post("/api/v1/auth/login", payload, format="json")


def test_login_with_device_registers_it_and_records_the_refresh_token(client):
    inst = _institution()
    _user(inst)

    response = _login(client, inst)

    assert response.status_code == 200
    assert Device.objects.filter(device_id="dev-1").count() == 1
    assert RefreshTokenRecord.objects.count() == 1


def test_refresh_rotates_and_returns_a_new_refresh_token(client):
    inst = _institution()
    _user(inst)
    first = _login(client, inst).json()["data"]

    response = client.post("/api/v1/auth/refresh", {"refresh": first["refresh"]}, format="json")

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["refresh"] != first["refresh"]
    assert body["access"]


def test_reusing_a_rotated_refresh_token_is_rejected_with_401(client):
    inst = _institution()
    _user(inst)
    first = _login(client, inst).json()["data"]
    client.post("/api/v1/auth/refresh", {"refresh": first["refresh"]}, format="json")

    response = client.post("/api/v1/auth/refresh", {"refresh": first["refresh"]}, format="json")

    assert response.status_code == 401
    assert RefreshTokenRecord.objects.filter(revoked_at__isnull=True).count() == 0


def test_logout_revokes_the_chain_so_refresh_stops_working(client):
    inst = _institution()
    _user(inst)
    tokens = _login(client, inst).json()["data"]

    logout = client.post("/api/v1/auth/logout", {"refresh": tokens["refresh"]}, format="json")
    assert logout.status_code == 200

    response = client.post("/api/v1/auth/refresh", {"refresh": tokens["refresh"]}, format="json")
    assert response.status_code == 401


def test_logout_leaves_other_devices_alone(client):
    inst = _institution()
    _user(inst)
    phone = _login(client, inst, device_id="dev-phone").json()["data"]
    tablet = _login(client, inst, device_id="dev-tablet").json()["data"]

    client.post("/api/v1/auth/logout", {"refresh": phone["refresh"]}, format="json")

    response = client.post("/api/v1/auth/refresh", {"refresh": tablet["refresh"]}, format="json")
    assert response.status_code == 200


def test_web_login_without_device_fields_still_works(client):
    inst = _institution()
    _user(inst)

    response = _login(client, inst, device_id=None)

    assert response.status_code == 200
    assert response.json()["data"]["access"]
    assert Device.objects.count() == 0


def test_web_refresh_of_an_untracked_token_still_works(client):
    inst = _institution()
    _user(inst)
    tokens = _login(client, inst, device_id=None).json()["data"]

    response = client.post("/api/v1/auth/refresh", {"refresh": tokens["refresh"]}, format="json")

    assert response.status_code == 200
    assert response.json()["data"]["access"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd services/auth-service && python -m pytest accounts/tests/test_mobile_auth_flow.py -v`
Expected: FAIL — device fields ignored, `Device.objects.count() == 0`, and `/logout` returns 404

- [ ] **Step 3: Extend the serializers**

In `services/auth-service/accounts/serializers.py`, add device fields to `LoginSerializer` (find the existing class and add these four fields to it):

```python
    device_id = serializers.CharField(max_length=64, required=False, allow_blank=False)
    platform = serializers.CharField(max_length=16, required=False, allow_blank=True, default="")
    model_name = serializers.CharField(
        max_length=128, required=False, allow_blank=True, default=""
    )
    push_token = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )
```

- [ ] **Step 4: Wire the views**

In `services/auth-service/accounts/views.py`, add to the imports:

```python
from accounts.token_service import (
    TokenInvalidError,
    TokenReuseError,
    issue_for_device,
    register_device,
    revoke_device_chain,
    rotate,
)
from accounts.models import RefreshTokenRecord
```

Replace the token-issuing tail of `LoginView.post` (currently `tokens = _issue_tokens(user)` at line 133) with:

```python
        device_id = serializer.validated_data.get("device_id")
        if device_id:
            device = register_device(
                user,
                device_id=device_id,
                platform=serializer.validated_data.get("platform", ""),
                model_name=serializer.validated_data.get("model_name", ""),
                push_token=serializer.validated_data.get("push_token", ""),
            )
            tokens = issue_for_device(user, device)
        else:
            # Web clients send no device — keep the stateless path unchanged.
            tokens = _issue_tokens(user)

        return ok(tokens, message="Login successful.")
```

Replace the whole body of `RefreshView.post` (lines 152-179) with:

```python
    def post(self, request):
        serializer = RefreshSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid refresh request.", errors=serializer.errors, status=400)

        raw = serializer.validated_data["refresh"]

        try:
            token = RefreshToken(raw)
        except TokenError as exc:
            return fail(f"Invalid or expired refresh token: {exc}", status=401)

        # Only mobile logins produce a tracked record. An untracked token is a
        # web client on the original stateless flow — rotate it in place.
        if not RefreshTokenRecord.objects.filter(jti=token["jti"]).exists():
            access = token.access_token
            access["sub"] = token.get("sub")
            access["role"] = token.get("role")
            access["tenant"] = token.get("tenant")

            data = {"access": str(access)}
            if settings.SIMPLE_JWT.get("ROTATE_REFRESH_TOKENS"):
                token.set_jti()
                token.set_exp()
                token.set_iat()
                data["refresh"] = str(token)
            return ok(data, message="Token refreshed.")

        try:
            tokens = rotate(raw)
        except TokenReuseError as exc:
            return fail(str(exc), status=401)
        except TokenInvalidError as exc:
            return fail(str(exc), status=401)

        return ok(tokens, message="Token refreshed.")


class LogoutView(APIView):
    """Revoke the presenting device's whole refresh chain.

    Unauthenticated by design: the refresh token in the body IS the proof of
    identity, and a client whose access token has already expired must still
    be able to log out.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = RefreshSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid logout request.", errors=serializer.errors, status=400)

        try:
            token = RefreshToken(serializer.validated_data["refresh"])
        except TokenError:
            # An unparseable token means there is nothing to revoke. Report
            # success so logout is never a dead end for the client.
            return ok(None, message="Logged out.")

        record = RefreshTokenRecord.objects.filter(jti=token["jti"]).first()
        if record is not None:
            revoke_device_chain(record.device)

        return ok(None, message="Logged out.")
```

- [ ] **Step 5: Add the route**

In `services/auth-service/accounts/urls.py`, add `LogoutView` to the import list and add this line after the `refresh` path:

```python
    path("logout", LogoutView.as_view(), name="auth-logout"),
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd services/auth-service && python -m pytest accounts/tests/ -v`
Expected: the 7 new tests PASS and every pre-existing auth test still PASSES

- [ ] **Step 7: Commit**

```bash
git add services/auth-service/accounts/views.py services/auth-service/accounts/serializers.py services/auth-service/accounts/urls.py services/auth-service/accounts/tests/test_mobile_auth_flow.py
git commit -m "feat(auth): device-bound login, rotating refresh, and logout"
```

---

## Task 5: Device list and revoke endpoints

**Files:**
- Modify: `services/auth-service/accounts/views.py` (add two views)
- Modify: `services/auth-service/accounts/serializers.py` (add `DeviceSerializer`)
- Modify: `services/auth-service/accounts/urls.py`
- Modify: `services/auth-service/accounts/tests/test_devices.py` (append)

**Interfaces:**
- Consumes: `Device` (Task 1), `revoke_device_chain` (Task 3).
- Produces: `GET /api/v1/auth/devices` returning `{"data": [{"device_id", "platform", "model_name", "last_seen_at", "is_stale"}]}`; `DELETE /api/v1/auth/devices/<device_id>` returning 200.

- [ ] **Step 1: Write the failing tests**

Append to `services/auth-service/accounts/tests/test_devices.py`:

```python
from rest_framework.test import APIClient

PASSWORD = "s3cur3-passw0rd"


def _login(client, institution, device_id, email="student@example.com"):
    return client.post(
        "/api/v1/auth/login",
        {
            "institution_slug": institution.slug,
            "email": email,
            "password": PASSWORD,
            "device_id": device_id,
            "platform": "android",
            "model_name": "Pixel 7",
        },
        format="json",
    )


def _authed_client(institution, user, device_id="dev-1"):
    client = APIClient()
    tokens = _login(client, institution, device_id, email=user.email).json()["data"]
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client, tokens


def test_device_list_returns_only_the_callers_devices():
    inst = _institution()
    alice = _user(inst, email="alice@example.com", user_code="STU-001")
    bob = _user(inst, email="bob@example.com", user_code="STU-002")
    _authed_client(inst, bob, device_id="bob-phone")
    client, _ = _authed_client(inst, alice, device_id="alice-phone")

    response = client.get("/api/v1/auth/devices")

    assert response.status_code == 200
    device_ids = [d["device_id"] for d in response.json()["data"]]
    assert device_ids == ["alice-phone"]


def test_revoking_a_device_kills_its_refresh_chain():
    inst = _institution()
    user = _user(inst)
    client, _ = _authed_client(inst, user, device_id="dev-phone")
    tablet_client = APIClient()
    tablet = _login(tablet_client, inst, "dev-tablet").json()["data"]

    response = client.delete("/api/v1/auth/devices/dev-tablet")
    assert response.status_code == 200

    refreshed = tablet_client.post(
        "/api/v1/auth/refresh", {"refresh": tablet["refresh"]}, format="json"
    )
    assert refreshed.status_code == 401


def test_revoking_an_unknown_device_returns_404():
    inst = _institution()
    user = _user(inst)
    client, _ = _authed_client(inst, user)

    response = client.delete("/api/v1/auth/devices/no-such-device")

    assert response.status_code == 404


def test_cannot_revoke_another_users_device():
    inst = _institution()
    alice = _user(inst, email="alice@example.com", user_code="STU-001")
    bob = _user(inst, email="bob@example.com", user_code="STU-002")
    _authed_client(inst, bob, device_id="bob-phone")
    client, _ = _authed_client(inst, alice, device_id="alice-phone")

    response = client.delete("/api/v1/auth/devices/bob-phone")

    assert response.status_code == 404
    assert Device.objects.get(device_id="bob-phone").refresh_tokens.filter(
        revoked_at__isnull=True
    ).exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd services/auth-service && python -m pytest accounts/tests/test_devices.py -v`
Expected: FAIL — the four new tests 404 on `/api/v1/auth/devices`

- [ ] **Step 3: Add the serializer**

Append to `services/auth-service/accounts/serializers.py`:

```python
class DeviceSerializer(serializers.Serializer):
    device_id = serializers.CharField()
    platform = serializers.CharField()
    model_name = serializers.CharField()
    last_seen_at = serializers.DateTimeField()
    is_stale = serializers.BooleanField()
```

- [ ] **Step 4: Add the views**

Add `DeviceSerializer` to the serializer imports in `services/auth-service/accounts/views.py`, add `Device` to the model imports, then append:

```python
class DeviceListView(APIView):
    """GET /api/v1/auth/devices — the caller's own registered devices."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        devices = Device.objects.filter(
            user_id=request.user.id, tenant_id=request.user.tenant_id
        ).order_by("-last_seen_at")
        return ok(DeviceSerializer(devices, many=True).data)


class DeviceRevokeView(APIView):
    """DELETE /api/v1/auth/devices/<device_id> — sign one device out.

    Scoped to the caller's own devices: a device_id belonging to someone else
    is reported as not found rather than forbidden, so the endpoint cannot be
    used to probe which device ids exist.
    """

    permission_classes = [IsAuthenticated]

    def delete(self, request, device_id):
        device = Device.objects.filter(
            user_id=request.user.id, tenant_id=request.user.tenant_id, device_id=device_id
        ).first()
        if device is None:
            return fail("Device not found.", status=404)

        revoke_device_chain(device)
        return ok(None, message="Device signed out.")
```

- [ ] **Step 5: Add the routes**

In `services/auth-service/accounts/urls.py`, import both views and add:

```python
    path("devices", DeviceListView.as_view(), name="auth-devices"),
    path("devices/<str:device_id>", DeviceRevokeView.as_view(), name="auth-device-revoke"),
```

- [ ] **Step 6: Run the full auth suite**

Run: `cd services/auth-service && python -m pytest accounts/tests/ -v`
Expected: all tests PASS, including every pre-existing one

- [ ] **Step 7: Commit**

```bash
git add services/auth-service/accounts/views.py services/auth-service/accounts/serializers.py services/auth-service/accounts/urls.py services/auth-service/accounts/tests/test_devices.py
git commit -m "feat(auth): add device list and per-device revoke endpoints"
```

---

## Task 6: Gateway routes for the new endpoints

**Files:**
- Modify: `gateway/nginx.conf` (or the auth location block — inspect first)

**Interfaces:**
- Consumes: the routes from Tasks 4–5.
- Produces: `/api/v1/auth/logout` and `/api/v1/auth/devices*` reachable through port 8080.

- [ ] **Step 1: Inspect the current auth routing**

Run: `grep -n "auth" gateway/nginx.conf`
Expected: an existing `location /api/v1/auth/` block that proxies to `auth-service:8000`

- [ ] **Step 2: Confirm whether any change is needed**

If the existing block is a prefix match on `/api/v1/auth/`, the new routes are already covered — record that in the commit message and skip to Step 4. If routes are listed individually, add `logout` and `devices` entries matching the existing style exactly.

- [ ] **Step 3: Verify through the gateway**

Run:
```bash
docker compose -f infra/docker-compose.yml up -d auth-service gateway postgres redis
curl -s -X POST http://localhost:8080/api/v1/auth/logout -H 'Content-Type: application/json' -d '{"refresh":"garbage"}'
```
Expected: `{"success":true,...,"message":"Logged out."}` — proves the route resolves through the gateway rather than 404ing at Nginx.

- [ ] **Step 4: Commit**

```bash
git add gateway/
git commit -m "chore(gateway): confirm auth logout and devices routing"
```

---

## Task 7: Expo app scaffold

**Files:**
- Create: `mobile/su-erp-app/` (Expo project)
- Create: `mobile/su-erp-app/.env.example`
- Modify: `.gitignore` (repo root) — ignore `mobile/su-erp-app/node_modules/`, `.expo/`

**Interfaces:**
- Produces: a runnable Expo TypeScript app with Expo Router, NativeWind, and a Jest setup. No app code beyond the router root yet.

- [ ] **Step 1: Scaffold the project**

Run:
```bash
cd mobile 2>/dev/null || mkdir -p mobile
cd /home/divanshub/Desktop/Capstone/mobile
npx create-expo-app@latest su-erp-app --template blank-typescript
```

- [ ] **Step 2: Install the dependencies**

Run:
```bash
cd /home/divanshub/Desktop/Capstone/mobile/su-erp-app
npx expo install expo-router expo-secure-store expo-sqlite expo-local-authentication expo-constants expo-linking
npm install @tanstack/react-query react-native-mmkv zustand nativewind
npm install -D tailwindcss@3 jest jest-expo @testing-library/react-native @types/jest
```

- [ ] **Step 3: Configure Expo Router as the entry point**

In `mobile/su-erp-app/package.json`, set:

```json
  "main": "expo-router/entry",
  "scripts": {
    "start": "expo start",
    "test": "jest",
    "lint": "expo lint"
  },
  "jest": {
    "preset": "jest-expo"
  }
```

- [ ] **Step 4: Add the environment template**

Create `mobile/su-erp-app/.env.example`:

```
# Gateway base URL. Use your machine's LAN IP for a physical device —
# localhost resolves to the phone itself, not your laptop.
EXPO_PUBLIC_API_BASE_URL=http://192.168.1.10:8080
```

- [ ] **Step 5: Create the router root**

Create `mobile/su-erp-app/app/_layout.tsx`:

```tsx
import { Stack } from 'expo-router';

export default function RootLayout() {
  return <Stack screenOptions={{ headerShown: false }} />;
}
```

Create `mobile/su-erp-app/app/index.tsx`:

```tsx
import { Text, View } from 'react-native';

export default function Index() {
  return (
    <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}>
      <Text>SU-ERP</Text>
    </View>
  );
}
```

Delete the scaffold's `App.tsx` if `create-expo-app` generated one — `expo-router/entry` replaces it.

- [ ] **Step 6: Verify it boots**

Run: `cd mobile/su-erp-app && npx expo start --no-dev --clear`
Expected: Metro starts and prints a QR code with no bundling errors. Press `q` to quit.

- [ ] **Step 7: Ignore build artifacts and commit**

Add to the repo-root `.gitignore`:

```
mobile/su-erp-app/node_modules/
mobile/su-erp-app/.expo/
mobile/su-erp-app/.env
```

```bash
git add mobile/ .gitignore
git commit -m "feat(mobile): scaffold Expo app with router, query, and test setup"
```

---

## Task 8: Shared API types

**Files:**
- Create: `shared/api-types/auth.ts`
- Create: `shared/api-types/envelope.ts`
- Create: `shared/api-types/index.ts`

**Interfaces:**
- Produces:
  - `ApiEnvelope<T>` = `{ success: boolean; data: T | null; message: string; errors: unknown }`
  - `Role` = `'student' | 'faculty' | 'warden' | 'driver' | 'admin' | 'alumni' | 'superadmin' | 'canteen_owner'`
  - `LoginRequest`, `TokenPair`, `MeResponse`, `DeviceSummary`

These names are consumed verbatim by Tasks 9–12.

- [ ] **Step 1: Write the envelope type**

Create `shared/api-types/envelope.ts`:

```ts
/** Every service wraps responses in this shape — see suerp_common/envelope.py. */
export interface ApiEnvelope<T> {
  success: boolean;
  data: T | null;
  message: string;
  errors: unknown;
}
```

- [ ] **Step 2: Write the auth types**

Create `shared/api-types/auth.ts`:

```ts
/** Mirrors accounts.models.User.Role. */
export type Role =
  | 'student'
  | 'faculty'
  | 'warden'
  | 'driver'
  | 'admin'
  | 'alumni'
  | 'superadmin'
  | 'canteen_owner';

export interface LoginRequest {
  institution_slug: string;
  email: string;
  password: string;
  /** Mobile only. Omitting these keeps the stateless web login path. */
  device_id?: string;
  platform?: string;
  model_name?: string;
  push_token?: string;
}

export interface TokenPair {
  access: string;
  refresh: string;
}

export interface MeResponse {
  user_code: string;
  email: string;
  role: Role;
  tenant: string;
}

export interface DeviceSummary {
  device_id: string;
  platform: string;
  model_name: string;
  last_seen_at: string;
  is_stale: boolean;
}

/** Claims carried by every access token. */
export interface JwtClaims {
  sub: string;
  role: Role;
  tenant: string;
  exp: number;
}
```

- [ ] **Step 3: Add the barrel export**

Create `shared/api-types/index.ts`:

```ts
export * from './auth';
export * from './envelope';
```

- [ ] **Step 4: Point the app's TypeScript at it**

In `mobile/su-erp-app/tsconfig.json`, add to `compilerOptions`:

```json
    "paths": {
      "@api-types/*": ["../../shared/api-types/*"],
      "@/*": ["./src/*"]
    }
```

- [ ] **Step 5: Verify it typechecks**

Run: `cd mobile/su-erp-app && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add shared/api-types/ mobile/su-erp-app/tsconfig.json
git commit -m "feat(shared): add API types shared by web and mobile"
```

---

## Task 9: Secure storage and device identity

**Files:**
- Create: `mobile/su-erp-app/src/lib/auth/storage.ts`
- Create: `mobile/su-erp-app/src/lib/device/identity.ts`
- Create: `mobile/su-erp-app/src/lib/device/__tests__/identity.test.ts`

**Interfaces:**
- Produces:
  - `storage.saveRefreshToken(token: string): Promise<void>`, `storage.readRefreshToken(): Promise<string | null>`, `storage.clearRefreshToken(): Promise<void>`
  - `identity.getDeviceId(): Promise<string>` — generates once, then stable
  - `identity.getPlatform(): string`, `identity.getModelName(): string`

- [ ] **Step 1: Write the failing test**

Create `mobile/su-erp-app/src/lib/device/__tests__/identity.test.ts`:

```ts
import { getDeviceId } from '../identity';

const store = new Map<string, string>();

jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn(async (k: string) => store.get(k) ?? null),
  setItemAsync: jest.fn(async (k: string, v: string) => {
    store.set(k, v);
  }),
  deleteItemAsync: jest.fn(async (k: string) => {
    store.delete(k);
  }),
}));

beforeEach(() => store.clear());

test('generates a device id on first call', async () => {
  const id = await getDeviceId();
  expect(id).toMatch(/^[0-9a-f-]{36}$/);
});

test('returns the same device id on every later call', async () => {
  const first = await getDeviceId();
  const second = await getDeviceId();
  expect(second).toBe(first);
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd mobile/su-erp-app && npx jest src/lib/device`
Expected: FAIL — `Cannot find module '../identity'`

- [ ] **Step 3: Write the storage module**

Create `mobile/su-erp-app/src/lib/auth/storage.ts`:

```ts
import * as SecureStore from 'expo-secure-store';

/**
 * The refresh token is the only credential written to disk, and it goes to
 * the Keychain/Keystore — never to MMKV or SQLite, which hold cached data
 * only. The access token is deliberately absent here: it lives in memory
 * for its 15-minute life and is re-derived by refreshing.
 */
const REFRESH_TOKEN_KEY = 'suerp.refresh_token';

export async function saveRefreshToken(token: string): Promise<void> {
  await SecureStore.setItemAsync(REFRESH_TOKEN_KEY, token);
}

export async function readRefreshToken(): Promise<string | null> {
  return SecureStore.getItemAsync(REFRESH_TOKEN_KEY);
}

export async function clearRefreshToken(): Promise<void> {
  await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY);
}
```

- [ ] **Step 4: Write the identity module**

Create `mobile/su-erp-app/src/lib/device/identity.ts`:

```ts
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

/**
 * A stable per-install identifier. The backend binds refresh chains to it
 * (see accounts/token_service.register_device), so it must survive app
 * restarts — hence SecureStore rather than in-memory state.
 */
const DEVICE_ID_KEY = 'suerp.device_id';

function uuidv4(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export async function getDeviceId(): Promise<string> {
  const existing = await SecureStore.getItemAsync(DEVICE_ID_KEY);
  if (existing) return existing;

  const generated = uuidv4();
  await SecureStore.setItemAsync(DEVICE_ID_KEY, generated);
  return generated;
}

export function getPlatform(): string {
  return Platform.OS;
}

export function getModelName(): string {
  return `${Platform.OS} ${Platform.Version}`;
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd mobile/su-erp-app && npx jest src/lib/device`
Expected: both tests PASS

- [ ] **Step 6: Commit**

```bash
git add mobile/su-erp-app/src/lib/auth/storage.ts mobile/su-erp-app/src/lib/device/ 
git commit -m "feat(mobile): add secure token storage and stable device identity"
```

---

## Task 10: API client with 401 refresh-and-retry

**Files:**
- Create: `mobile/su-erp-app/src/lib/api/client.ts`
- Create: `mobile/su-erp-app/src/lib/api/auth.ts`
- Create: `mobile/su-erp-app/src/lib/api/__tests__/client.test.ts`

**Interfaces:**
- Consumes: `ApiEnvelope`, `TokenPair`, `LoginRequest`, `MeResponse`, `DeviceSummary` (Task 8); `readRefreshToken`, `saveRefreshToken`, `clearRefreshToken` (Task 9).
- Produces:
  - `class ApiError extends Error` with `status: number` and `requestId: string | null`
  - `setAccessToken(token: string | null): void`, `getAccessToken(): string | null`
  - `setOnAuthFailure(handler: () => void): void`
  - `request<T>(path: string, init?: RequestInit & { idempotencyKey?: string }): Promise<T>` — unwraps the envelope, returns `data`
  - `login(body: LoginRequest): Promise<TokenPair>`, `refreshTokens(): Promise<TokenPair>`, `logout(): Promise<void>`, `fetchMe(): Promise<MeResponse>`, `listDevices(): Promise<DeviceSummary[]>`, `revokeDevice(deviceId: string): Promise<void>`

- [ ] **Step 1: Write the failing tests**

Create `mobile/su-erp-app/src/lib/api/__tests__/client.test.ts`:

```ts
import { ApiError, request, setAccessToken } from '../client';

const store = new Map<string, string>();
jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn(async (k: string) => store.get(k) ?? null),
  setItemAsync: jest.fn(async (k: string, v: string) => {
    store.set(k, v);
  }),
  deleteItemAsync: jest.fn(async (k: string) => {
    store.delete(k);
  }),
}));

function envelope(data: unknown, ok = true) {
  return {
    ok: true,
    status: 200,
    json: async () => ({ success: ok, data, message: '', errors: null }),
  };
}

beforeEach(() => {
  store.clear();
  setAccessToken(null);
  global.fetch = jest.fn();
});

test('unwraps the envelope and returns data', async () => {
  (global.fetch as jest.Mock).mockResolvedValueOnce(envelope({ user_code: 'STU-001' }));

  const result = await request<{ user_code: string }>('/api/v1/auth/me');

  expect(result.user_code).toBe('STU-001');
});

test('sends the bearer token when one is set', async () => {
  setAccessToken('access-1');
  (global.fetch as jest.Mock).mockResolvedValueOnce(envelope({}));

  await request('/api/v1/auth/me');

  const headers = (global.fetch as jest.Mock).mock.calls[0][1].headers;
  expect(headers.Authorization).toBe('Bearer access-1');
});

test('sends an X-Request-Id on every call', async () => {
  (global.fetch as jest.Mock).mockResolvedValueOnce(envelope({}));

  await request('/api/v1/auth/me');

  const headers = (global.fetch as jest.Mock).mock.calls[0][1].headers;
  expect(headers['X-Request-Id']).toMatch(/^[0-9a-f-]{36}$/);
});

test('refreshes once and retries after a 401', async () => {
  store.set('suerp.refresh_token', 'refresh-1');
  setAccessToken('expired');
  (global.fetch as jest.Mock)
    .mockResolvedValueOnce({ ok: false, status: 401, json: async () => ({}) })
    .mockResolvedValueOnce(envelope({ access: 'access-2', refresh: 'refresh-2' }))
    .mockResolvedValueOnce(envelope({ user_code: 'STU-001' }));

  const result = await request<{ user_code: string }>('/api/v1/auth/me');

  expect(result.user_code).toBe('STU-001');
  expect((global.fetch as jest.Mock).mock.calls).toHaveLength(3);
});

test('a second 401 clears the session and throws', async () => {
  store.set('suerp.refresh_token', 'refresh-1');
  setAccessToken('expired');
  (global.fetch as jest.Mock)
    .mockResolvedValueOnce({ ok: false, status: 401, json: async () => ({}) })
    .mockResolvedValueOnce({ ok: false, status: 401, json: async () => ({}) });

  await expect(request('/api/v1/auth/me')).rejects.toBeInstanceOf(ApiError);
  expect(store.has('suerp.refresh_token')).toBe(false);
});

test('sends the idempotency key when given one', async () => {
  (global.fetch as jest.Mock).mockResolvedValueOnce(envelope({}));

  await request('/api/v1/grievance/tickets', {
    method: 'POST',
    idempotencyKey: 'key-1',
  });

  const headers = (global.fetch as jest.Mock).mock.calls[0][1].headers;
  expect(headers['Idempotency-Key']).toBe('key-1');
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd mobile/su-erp-app && npx jest src/lib/api`
Expected: FAIL — `Cannot find module '../client'`

- [ ] **Step 3: Write the client**

Create `mobile/su-erp-app/src/lib/api/client.ts`:

```ts
import type { ApiEnvelope, TokenPair } from '@api-types/index';

import { clearRefreshToken, readRefreshToken, saveRefreshToken } from '../auth/storage';

const BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL ?? 'http://localhost:8080';

/**
 * The access token is held here, in memory, for exactly this reason: it has a
 * 15-minute life and writing it to disk would widen the blast radius of a
 * compromised device for no benefit. Only the refresh token is persisted,
 * and only to SecureStore.
 */
let accessToken: string | null = null;
let onAuthFailure: (() => void) | null = null;
/** Concurrent 401s must not each fire their own refresh — they share this. */
let inFlightRefresh: Promise<TokenPair> | null = null;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly requestId: string | null = null,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function setOnAuthFailure(handler: () => void): void {
  onAuthFailure = handler;
}

function requestId(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

async function refreshTokenPair(): Promise<TokenPair> {
  const refresh = await readRefreshToken();
  if (!refresh) throw new ApiError('No refresh token.', 401);

  const response = await fetch(`${BASE_URL}/api/v1/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Request-Id': requestId() },
    body: JSON.stringify({ refresh }),
  });

  if (!response.ok) throw new ApiError('Refresh rejected.', response.status);

  const body = (await response.json()) as ApiEnvelope<TokenPair>;
  if (!body.data) throw new ApiError('Refresh returned no tokens.', 401);

  setAccessToken(body.data.access);
  await saveRefreshToken(body.data.refresh);
  return body.data;
}

/** Deduplicates concurrent refreshes so one 401 storm makes one round-trip. */
function refreshOnce(): Promise<TokenPair> {
  if (!inFlightRefresh) {
    inFlightRefresh = refreshTokenPair().finally(() => {
      inFlightRefresh = null;
    });
  }
  return inFlightRefresh;
}

async function endSession(): Promise<void> {
  setAccessToken(null);
  await clearRefreshToken();
  onAuthFailure?.();
}

export interface RequestOptions extends RequestInit {
  /** Sent as Idempotency-Key so a replayed queued mutation is a no-op. */
  idempotencyKey?: string;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { idempotencyKey, ...init } = options;

  const send = async (): Promise<Response> => {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'X-Request-Id': requestId(),
      ...((init.headers as Record<string, string>) ?? {}),
    };
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
    if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey;

    return fetch(`${BASE_URL}${path}`, { ...init, headers });
  };

  let response = await send();

  if (response.status === 401) {
    try {
      await refreshOnce();
    } catch {
      await endSession();
      throw new ApiError('Session expired.', 401);
    }
    response = await send();
    if (response.status === 401) {
      await endSession();
      throw new ApiError('Session expired.', 401);
    }
  }

  const body = (await response.json()) as ApiEnvelope<T>;

  if (!response.ok || !body.success) {
    throw new ApiError(
      body?.message || `Request failed (${response.status})`,
      response.status,
      response.headers?.get?.('X-Request-Id') ?? null,
    );
  }

  return body.data as T;
}

export { refreshOnce as refreshSession };
```

- [ ] **Step 4: Write the auth API module**

Create `mobile/su-erp-app/src/lib/api/auth.ts`:

```ts
import type { DeviceSummary, LoginRequest, MeResponse, TokenPair } from '@api-types/index';

import { clearRefreshToken, readRefreshToken, saveRefreshToken } from '../auth/storage';
import { request, setAccessToken } from './client';

export async function login(body: LoginRequest): Promise<TokenPair> {
  const tokens = await request<TokenPair>('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  setAccessToken(tokens.access);
  await saveRefreshToken(tokens.refresh);
  return tokens;
}

export async function logout(): Promise<void> {
  const refresh = await readRefreshToken();
  if (refresh) {
    // Best-effort: a failed logout call must still clear local credentials,
    // otherwise a network blip leaves the user stuck signed in.
    try {
      await request('/api/v1/auth/logout', {
        method: 'POST',
        body: JSON.stringify({ refresh }),
      });
    } catch {
      // intentionally ignored — local cleanup below is what matters
    }
  }
  setAccessToken(null);
  await clearRefreshToken();
}

export function fetchMe(): Promise<MeResponse> {
  return request<MeResponse>('/api/v1/auth/me');
}

export function listDevices(): Promise<DeviceSummary[]> {
  return request<DeviceSummary[]>('/api/v1/auth/devices');
}

export function revokeDevice(deviceId: string): Promise<void> {
  return request<void>(`/api/v1/auth/devices/${deviceId}`, { method: 'DELETE' });
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd mobile/su-erp-app && npx jest src/lib/api`
Expected: all 6 tests PASS

- [ ] **Step 6: Commit**

```bash
git add mobile/su-erp-app/src/lib/api/
git commit -m "feat(mobile): add API client with envelope unwrapping and 401 retry"
```

---

## Task 11: Offline mutation queue

**Files:**
- Create: `mobile/su-erp-app/src/lib/offline/queue.ts`
- Create: `mobile/su-erp-app/src/lib/offline/__tests__/queue.test.ts`

**Interfaces:**
- Consumes: `request`, `ApiError` (Task 10).
- Produces:
  - `interface QueuedMutation { id: string; endpoint: string; method: string; body: string; attempts: number; createdAt: number; status: 'pending' | 'failed' }`
  - `enqueue(endpoint: string, method: string, body: unknown): Promise<QueuedMutation>`
  - `list(): Promise<QueuedMutation[]>`
  - `replay(): Promise<{ sent: number; dropped: number; failed: number }>`
  - `discard(id: string): Promise<void>`
  - `MAX_ATTEMPTS = 5`
- Storage: an injectable store so tests run without a device. `setStore(store: QueueStore)` swaps the SQLite implementation for an in-memory one.

- [ ] **Step 1: Write the failing tests**

Create `mobile/su-erp-app/src/lib/offline/__tests__/queue.test.ts`:

```ts
import { ApiError } from '../../api/client';
import { MAX_ATTEMPTS, createMemoryStore, enqueue, list, replay, setStore } from '../queue';

jest.mock('../../api/client', () => {
  class MockApiError extends Error {
    constructor(
      message: string,
      readonly status: number,
    ) {
      super(message);
    }
  }
  return { request: jest.fn(), ApiError: MockApiError };
});

const { request } = jest.requireMock('../../api/client');

beforeEach(() => {
  setStore(createMemoryStore());
  request.mockReset();
});

test('enqueued mutations get a uuid idempotency key', async () => {
  const row = await enqueue('/api/v1/attendance/mark', 'POST', { session: 'S1' });
  expect(row.id).toMatch(/^[0-9a-f-]{36}$/);
});

test('replay sends pending mutations and clears them', async () => {
  request.mockResolvedValue({});
  await enqueue('/api/v1/attendance/mark', 'POST', { session: 'S1' });

  const result = await replay();

  expect(result.sent).toBe(1);
  expect(await list()).toHaveLength(0);
});

test('replay sends the row id as the idempotency key', async () => {
  request.mockResolvedValue({});
  const row = await enqueue('/api/v1/attendance/mark', 'POST', { session: 'S1' });

  await replay();

  expect(request).toHaveBeenCalledWith(
    '/api/v1/attendance/mark',
    expect.objectContaining({ idempotencyKey: row.id }),
  );
});

test('replay preserves insertion order', async () => {
  request.mockResolvedValue({});
  await enqueue('/first', 'POST', {});
  await enqueue('/second', 'POST', {});

  await replay();

  expect(request.mock.calls.map((c: unknown[]) => c[0])).toEqual(['/first', '/second']);
});

test('a 409 drops the mutation instead of retrying it', async () => {
  request.mockRejectedValue(new ApiError('Already completed.', 409));
  await enqueue('/api/v1/orders/1/status', 'POST', { status: 'completed' });

  const result = await replay();

  expect(result.dropped).toBe(1);
  expect(await list()).toHaveLength(0);
});

test('a 422 also drops the mutation', async () => {
  request.mockRejectedValue(new ApiError('Unprocessable.', 422));
  await enqueue('/api/v1/orders/1/status', 'POST', { status: 'completed' });

  await replay();

  expect(await list()).toHaveLength(0);
});

test('a 500 keeps the mutation and counts an attempt', async () => {
  request.mockRejectedValue(new ApiError('Server error.', 500));
  await enqueue('/api/v1/attendance/mark', 'POST', {});

  await replay();

  const [row] = await list();
  expect(row.attempts).toBe(1);
  expect(row.status).toBe('pending');
});

test('a mutation is marked failed after the attempt limit', async () => {
  request.mockRejectedValue(new ApiError('Server error.', 500));
  await enqueue('/api/v1/attendance/mark', 'POST', {});

  for (let i = 0; i < MAX_ATTEMPTS; i += 1) await replay();

  const [row] = await list();
  expect(row.attempts).toBe(MAX_ATTEMPTS);
  expect(row.status).toBe('failed');
});

test('failed mutations are skipped by later replays', async () => {
  request.mockRejectedValue(new ApiError('Server error.', 500));
  await enqueue('/api/v1/attendance/mark', 'POST', {});
  for (let i = 0; i < MAX_ATTEMPTS; i += 1) await replay();
  request.mockReset();

  await replay();

  expect(request).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd mobile/su-erp-app && npx jest src/lib/offline`
Expected: FAIL — `Cannot find module '../queue'`

- [ ] **Step 3: Write the queue**

Create `mobile/su-erp-app/src/lib/offline/queue.ts`:

```ts
import { ApiError, request } from '../api/client';

/**
 * Field-ops mutations captured offline and replayed on reconnect.
 *
 * Only mutations that genuinely happen in dead zones belong here — marking
 * attendance, advancing an order, scanning a pass, logging a visitor, filing
 * a grievance, batching GPS breadcrumbs. Payments deliberately do NOT queue:
 * a fee payment that silently fires an hour later is worse than one that
 * fails loudly now.
 *
 * `id` is generated at capture time and travels as the Idempotency-Key, so a
 * double replay is a no-op on the server side.
 */
export const MAX_ATTEMPTS = 5;

/** Server rejections that mean "this will never succeed" — drop, never retry. */
const TERMINAL_STATUSES = [400, 403, 404, 409, 422];

export interface QueuedMutation {
  id: string;
  endpoint: string;
  method: string;
  body: string;
  attempts: number;
  createdAt: number;
  status: 'pending' | 'failed';
}

export interface QueueStore {
  insert(row: QueuedMutation): Promise<void>;
  all(): Promise<QueuedMutation[]>;
  update(row: QueuedMutation): Promise<void>;
  remove(id: string): Promise<void>;
}

export function createMemoryStore(): QueueStore {
  let rows: QueuedMutation[] = [];
  return {
    async insert(row) {
      rows.push(row);
    },
    async all() {
      return [...rows];
    },
    async update(row) {
      rows = rows.map((r) => (r.id === row.id ? row : r));
    },
    async remove(id) {
      rows = rows.filter((r) => r.id !== id);
    },
  };
}

let store: QueueStore = createMemoryStore();

export function setStore(next: QueueStore): void {
  store = next;
}

function uuidv4(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export async function enqueue(
  endpoint: string,
  method: string,
  body: unknown,
): Promise<QueuedMutation> {
  const row: QueuedMutation = {
    id: uuidv4(),
    endpoint,
    method,
    body: JSON.stringify(body),
    attempts: 0,
    createdAt: Date.now(),
    status: 'pending',
  };
  await store.insert(row);
  return row;
}

export function list(): Promise<QueuedMutation[]> {
  return store.all();
}

export function discard(id: string): Promise<void> {
  return store.remove(id);
}

export async function replay(): Promise<{ sent: number; dropped: number; failed: number }> {
  const rows = (await store.all())
    .filter((r) => r.status === 'pending')
    .sort((a, b) => a.createdAt - b.createdAt);

  let sent = 0;
  let dropped = 0;
  let failed = 0;

  for (const row of rows) {
    try {
      await request(row.endpoint, {
        method: row.method,
        body: row.body,
        idempotencyKey: row.id,
      });
      await store.remove(row.id);
      sent += 1;
    } catch (error) {
      const status = error instanceof ApiError ? error.status : 0;

      if (TERMINAL_STATUSES.includes(status)) {
        // The server has ruled on this: someone else advanced the order, the
        // ticket vanished, the payload is bad. Retrying cannot change that.
        await store.remove(row.id);
        dropped += 1;
        continue;
      }

      const attempts = row.attempts + 1;
      const next: QueuedMutation = {
        ...row,
        attempts,
        status: attempts >= MAX_ATTEMPTS ? 'failed' : 'pending',
      };
      await store.update(next);
      if (next.status === 'failed') failed += 1;
    }
  }

  return { sent, dropped, failed };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd mobile/su-erp-app && npx jest src/lib/offline`
Expected: all 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add mobile/su-erp-app/src/lib/offline/
git commit -m "feat(mobile): add offline mutation queue with idempotent replay"
```

---

## Task 12: Session store and login screen

**Files:**
- Create: `mobile/su-erp-app/src/lib/auth/session.ts`
- Create: `mobile/su-erp-app/src/lib/auth/__tests__/session.test.ts`
- Create: `mobile/su-erp-app/app/(auth)/login.tsx`
- Modify: `mobile/su-erp-app/app/index.tsx`
- Modify: `mobile/su-erp-app/app/_layout.tsx`

**Interfaces:**
- Consumes: `login`, `logout`, `fetchMe` (Task 10); `getDeviceId`, `getPlatform`, `getModelName` (Task 9); `Role`, `MeResponse` (Task 8).
- Produces: `useSession()` Zustand store with `{ status: 'loading' | 'signed-out' | 'signed-in', user: MeResponse | null, signIn(slug, email, password): Promise<void>, signOut(): Promise<void>, restore(): Promise<void> }`, plus `roleHome(role: Role): string` mapping a role to its route.

- [ ] **Step 1: Write the failing tests**

Create `mobile/su-erp-app/src/lib/auth/__tests__/session.test.ts`:

```ts
import { roleHome, useSession } from '../session';

jest.mock('../../api/auth', () => ({
  login: jest.fn(),
  logout: jest.fn(),
  fetchMe: jest.fn(),
}));
jest.mock('../../device/identity', () => ({
  getDeviceId: jest.fn(async () => 'dev-1'),
  getPlatform: jest.fn(() => 'android'),
  getModelName: jest.fn(() => 'Pixel 7'),
}));
jest.mock('../storage', () => ({
  readRefreshToken: jest.fn(async () => null),
  clearRefreshToken: jest.fn(async () => {}),
  saveRefreshToken: jest.fn(async () => {}),
}));

const api = jest.requireMock('../../api/auth');

beforeEach(() => {
  useSession.setState({ status: 'loading', user: null });
  jest.clearAllMocks();
});

test('signIn stores the user and marks the session signed in', async () => {
  api.login.mockResolvedValue({ access: 'a', refresh: 'r' });
  api.fetchMe.mockResolvedValue({
    user_code: 'STU-001',
    email: 'student@example.com',
    role: 'student',
    tenant: 'tenant-uuid',
  });

  await useSession.getState().signIn('alpha', 'student@example.com', 'pw');

  const state = useSession.getState();
  expect(state.status).toBe('signed-in');
  expect(state.user?.role).toBe('student');
});

test('signIn sends the device identity with the credentials', async () => {
  api.login.mockResolvedValue({ access: 'a', refresh: 'r' });
  api.fetchMe.mockResolvedValue({
    user_code: 'STU-001',
    email: 'student@example.com',
    role: 'student',
    tenant: 't',
  });

  await useSession.getState().signIn('alpha', 'student@example.com', 'pw');

  expect(api.login).toHaveBeenCalledWith(
    expect.objectContaining({ device_id: 'dev-1', platform: 'android' }),
  );
});

test('signOut clears the user', async () => {
  api.logout.mockResolvedValue(undefined);
  useSession.setState({
    status: 'signed-in',
    user: { user_code: 'STU-001', email: 'e', role: 'student', tenant: 't' },
  });

  await useSession.getState().signOut();

  expect(useSession.getState().status).toBe('signed-out');
  expect(useSession.getState().user).toBeNull();
});

test('restore with no stored refresh token lands signed out', async () => {
  await useSession.getState().restore();
  expect(useSession.getState().status).toBe('signed-out');
});

test('roleHome maps each app role to its shell', () => {
  expect(roleHome('student')).toBe('/(student)');
  expect(roleHome('warden')).toBe('/(warden)');
  expect(roleHome('driver')).toBe('/(driver)');
  expect(roleHome('canteen_owner')).toBe('/(canteen-owner)');
});

test('roleHome sends web-only roles to the unsupported screen', () => {
  expect(roleHome('admin')).toBe('/unsupported-role');
  expect(roleHome('superadmin')).toBe('/unsupported-role');
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd mobile/su-erp-app && npx jest src/lib/auth`
Expected: FAIL — `Cannot find module '../session'`

- [ ] **Step 3: Write the session store**

Create `mobile/su-erp-app/src/lib/auth/session.ts`:

```ts
import type { MeResponse, Role } from '@api-types/index';
import { create } from 'zustand';

import { fetchMe, login as apiLogin, logout as apiLogout } from '../api/auth';
import { refreshSession, setAccessToken } from '../api/client';
import { getDeviceId, getModelName, getPlatform } from '../device/identity';
import { readRefreshToken } from './storage';

/** Roles the app supports. Everyone else is directed to the web portal. */
const ROLE_HOMES: Partial<Record<Role, string>> = {
  student: '/(student)',
  warden: '/(warden)',
  driver: '/(driver)',
  canteen_owner: '/(canteen-owner)',
};

export function roleHome(role: Role): string {
  return ROLE_HOMES[role] ?? '/unsupported-role';
}

interface SessionState {
  status: 'loading' | 'signed-out' | 'signed-in';
  user: MeResponse | null;
  signIn(institutionSlug: string, email: string, password: string): Promise<void>;
  signOut(): Promise<void>;
  restore(): Promise<void>;
}

export const useSession = create<SessionState>((set) => ({
  status: 'loading',
  user: null,

  async signIn(institutionSlug, email, password) {
    await apiLogin({
      institution_slug: institutionSlug,
      email,
      password,
      device_id: await getDeviceId(),
      platform: getPlatform(),
      model_name: getModelName(),
    });
    set({ user: await fetchMe(), status: 'signed-in' });
  },

  async signOut() {
    await apiLogout();
    set({ user: null, status: 'signed-out' });
  },

  /**
   * Cold start: the access token died with the last process, so the stored
   * refresh token is the only way back in. A rejected refresh means the
   * device was revoked or the chain was reused — sign out rather than retry.
   */
  async restore() {
    const refresh = await readRefreshToken();
    if (!refresh) {
      set({ status: 'signed-out', user: null });
      return;
    }

    try {
      await refreshSession();
      set({ user: await fetchMe(), status: 'signed-in' });
    } catch {
      setAccessToken(null);
      set({ status: 'signed-out', user: null });
    }
  },
}));
```

- [ ] **Step 4: Run the store tests**

Run: `cd mobile/su-erp-app && npx jest src/lib/auth`
Expected: all 6 tests PASS

- [ ] **Step 5: Write the login screen**

Create `mobile/su-erp-app/app/(auth)/login.tsx`:

```tsx
import { router } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, Pressable, Text, TextInput, View } from 'react-native';

import { roleHome, useSession } from '@/lib/auth/session';

export default function LoginScreen() {
  const signIn = useSession((s) => s.signIn);
  const [institutionSlug, setInstitutionSlug] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await signIn(institutionSlug.trim(), email.trim(), password);
      const user = useSession.getState().user;
      if (user) router.replace(roleHome(user.role));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Login failed.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <View style={{ flex: 1, justifyContent: 'center', padding: 24, gap: 12 }}>
      <Text style={{ fontSize: 28, fontWeight: '600', marginBottom: 12 }}>SU-ERP</Text>

      <TextInput
        placeholder="Institution"
        autoCapitalize="none"
        value={institutionSlug}
        onChangeText={setInstitutionSlug}
        style={{ borderWidth: 1, borderColor: '#ccc', borderRadius: 8, padding: 12 }}
      />
      <TextInput
        placeholder="Email"
        autoCapitalize="none"
        keyboardType="email-address"
        value={email}
        onChangeText={setEmail}
        style={{ borderWidth: 1, borderColor: '#ccc', borderRadius: 8, padding: 12 }}
      />
      <TextInput
        placeholder="Password"
        secureTextEntry
        value={password}
        onChangeText={setPassword}
        style={{ borderWidth: 1, borderColor: '#ccc', borderRadius: 8, padding: 12 }}
      />

      {error ? <Text style={{ color: '#b00020' }}>{error}</Text> : null}

      <Pressable
        onPress={submit}
        disabled={busy}
        style={{ backgroundColor: '#1d4ed8', borderRadius: 8, padding: 14, alignItems: 'center' }}
      >
        {busy ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={{ color: '#fff', fontWeight: '600' }}>Sign in</Text>
        )}
      </Pressable>
    </View>
  );
}
```

- [ ] **Step 6: Write the boot gate and the unsupported-role screen**

Replace `mobile/su-erp-app/app/index.tsx`:

```tsx
import { Redirect } from 'expo-router';
import { useEffect } from 'react';
import { ActivityIndicator, View } from 'react-native';

import { roleHome, useSession } from '@/lib/auth/session';

export default function Index() {
  const { status, user, restore } = useSession();

  useEffect(() => {
    void restore();
  }, [restore]);

  if (status === 'loading') {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}>
        <ActivityIndicator />
      </View>
    );
  }

  if (status === 'signed-out' || !user) return <Redirect href="/(auth)/login" />;

  return <Redirect href={roleHome(user.role)} />;
}
```

Create `mobile/su-erp-app/app/unsupported-role.tsx`:

```tsx
import { Pressable, Text, View } from 'react-native';

import { useSession } from '@/lib/auth/session';

export default function UnsupportedRole() {
  const signOut = useSession((s) => s.signOut);

  return (
    <View style={{ flex: 1, justifyContent: 'center', padding: 24, gap: 16 }}>
      <Text style={{ fontSize: 20, fontWeight: '600' }}>Use the web portal</Text>
      <Text>
        Admin and superadmin tools are only available on the SU-ERP web app. Sign in there to
        manage your institution.
      </Text>
      <Pressable onPress={() => void signOut()}>
        <Text style={{ color: '#1d4ed8', fontWeight: '600' }}>Sign out</Text>
      </Pressable>
    </View>
  );
}
```

- [ ] **Step 7: Add the four role shells**

For each of `student`, `warden`, `driver`, `canteen-owner`, create
`mobile/su-erp-app/app/(<role>)/_layout.tsx`:

```tsx
import { Stack } from 'expo-router';

export default function RoleLayout() {
  return <Stack />;
}
```

and `mobile/su-erp-app/app/(<role>)/index.tsx` (substituting the role name in the heading):

```tsx
import { Text, View } from 'react-native';

import { useSession } from '@/lib/auth/session';

export default function Home() {
  const user = useSession((s) => s.user);

  return (
    <View style={{ flex: 1, padding: 24, gap: 8 }}>
      <Text style={{ fontSize: 22, fontWeight: '600' }}>Student</Text>
      <Text>{user?.email}</Text>
      <Text>{user?.user_code}</Text>
    </View>
  );
}
```

- [ ] **Step 8: Wire the auth-failure handler**

Replace `mobile/su-erp-app/app/_layout.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Stack, router } from 'expo-router';
import { useEffect } from 'react';

import { setOnAuthFailure } from '@/lib/api/client';
import { useSession } from '@/lib/auth/session';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
});

export default function RootLayout() {
  useEffect(() => {
    // A refresh that cannot be recovered (revoked device, reused token)
    // must land the user on the login screen rather than an empty shell.
    setOnAuthFailure(() => {
      useSession.setState({ status: 'signed-out', user: null });
      router.replace('/(auth)/login');
    });
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <Stack screenOptions={{ headerShown: false }} />
    </QueryClientProvider>
  );
}
```

- [ ] **Step 9: Verify the whole app suite and typecheck**

Run: `cd mobile/su-erp-app && npx tsc --noEmit && npx jest`
Expected: no type errors; every test PASSES

- [ ] **Step 10: Commit**

```bash
git add mobile/su-erp-app/app mobile/su-erp-app/src/lib/auth/
git commit -m "feat(mobile): add session store, login screen, and role routing"
```

---

## Task 13: End-to-end verification against the running stack

**Files:**
- Create: `docs/RUNBOOK-mobile.md`

**Interfaces:**
- Consumes: everything above.
- Produces: a written record that login, rotation, and revoke work against real services.

- [ ] **Step 1: Start the backend**

Run:
```bash
docker compose -f infra/docker-compose.yml up -d postgres redis rabbitmq auth-service gateway
docker compose -f infra/docker-compose.yml exec auth-service python manage.py migrate
```
Expected: the two new migrations apply cleanly.

- [ ] **Step 2: Exercise the mobile flow with curl**

Run:
```bash
BASE=http://localhost:8080/api/v1/auth
TOKENS=$(curl -s -X POST $BASE/login -H 'Content-Type: application/json' \
  -d '{"institution_slug":"alpha","email":"student@example.com","password":"s3cur3-passw0rd","device_id":"curl-device","platform":"android","model_name":"curl"}')
echo "$TOKENS"
REFRESH=$(echo "$TOKENS" | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["refresh"])')
curl -s -X POST $BASE/refresh -H 'Content-Type: application/json' -d "{\"refresh\":\"$REFRESH\"}"
curl -s -X POST $BASE/refresh -H 'Content-Type: application/json' -d "{\"refresh\":\"$REFRESH\"}"
```
Expected: login 200 with both tokens; first refresh 200 with a new pair; **second refresh 401** with a message about the chain being revoked. If a seeded student does not exist, create one first via the superadmin/admin flow in `docs/RUNBOOK.md`.

- [ ] **Step 3: Run the app against it**

Run: `cd mobile/su-erp-app && cp .env.example .env` then edit `.env` to your LAN IP, then `npx expo start`.
Open the app on a device or emulator, log in with the same credentials, and confirm you land on the student home screen showing your email and user code.

- [ ] **Step 4: Confirm revoke ends the session**

With the app signed in, run:
```bash
curl -s -X DELETE http://localhost:8080/api/v1/auth/devices/<the-app-device-id> \
  -H "Authorization: Bearer <an-access-token>"
```
Then force the app's token to expire (wait 15 minutes, or restart the app to trigger `restore()`).
Expected: the app returns to the login screen rather than showing a stale shell.

- [ ] **Step 5: Write the runbook**

Create `docs/RUNBOOK-mobile.md` recording: the compose profile needed, the `.env` LAN-IP gotcha, the curl sequence from Step 2 with its real output, and the revoke check from Step 4.

- [ ] **Step 6: Run the full backend suite one more time**

Run: `cd services/auth-service && python -m pytest accounts/ -v`
Expected: every test PASSES, including all pre-existing ones.

- [ ] **Step 7: Commit**

```bash
git add docs/RUNBOOK-mobile.md
git commit -m "docs: add mobile runbook with verified auth flow"
```

---

## Out of scope for Phase 1

These are spec'd in `docs/superpowers/specs/2026-08-02-mobile-app-design.md` and get their own plans:

- **Phase 2** — student surface: hostel, fees, canteen, transport, grievance, notifications, plus the read-cache MMKV persister wired to real queries
- **Phase 3** — warden, driver, and canteen-owner surfaces, plus the backend gaps they need (`VisitorLog`, driver trip endpoints, grievance `PATCH /status`)
- **Phase 4** — hardware features: QR e-pass, geofenced attendance, live bus tracking, biometric payment gate, camera grievance with the 7-day purge sweep, pickup token, widgets, document vault
- **Push notifications** — the `push-channel` consumer in `notification-service`. The `Device.push_token` column ships in Task 1 so the app can register a token before the consumer exists.
