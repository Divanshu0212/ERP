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


from rest_framework.test import APIClient  # noqa: E402

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
    assert (
        Device.objects.get(device_id="bob-phone")
        .refresh_tokens.filter(revoked_at__isnull=True)
        .exists()
    )
