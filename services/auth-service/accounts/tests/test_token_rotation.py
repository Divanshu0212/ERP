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
