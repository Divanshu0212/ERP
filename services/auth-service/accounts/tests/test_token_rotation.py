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


from accounts.token_service import (  # noqa: E402
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
    claims = jwt.decode(tokens["access"], settings.SIMPLE_JWT["SIGNING_KEY"], algorithms=["HS256"])

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
