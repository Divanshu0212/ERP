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
