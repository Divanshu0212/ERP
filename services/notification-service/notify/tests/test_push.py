"""Push delivery alongside the in-app inbox.

The inbox row is the source of truth; push is best-effort on top of it. These
tests pin that ordering: a push outage must never cost a notification.
"""

import uuid
from unittest.mock import patch

import pytest
from notify.consumers import dispatch_event
from notify.models import Notification, PushDevice
from notify.push import ExpoPushChannel, NullPushChannel, get_channel
from rest_framework.test import APIClient
from suerp_common.events import build_event

pytestmark = pytest.mark.django_db

TENANT_A = uuid.uuid4()


def _client(tenant_id, role="student", sub="STU-001"):
    import jwt  # noqa: PLC0415
    from django.conf import settings  # noqa: PLC0415

    token = jwt.encode(
        {"sub": str(sub), "role": role, "tenant": str(tenant_id)},
        settings.JWT_SIGNING_KEY,
        algorithm="HS256",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _payment_event(tenant_id, student="STU-001"):
    return build_event(
        "finance.payment.success",
        tenant_id=str(tenant_id),
        payload={
            "invoice_id": str(uuid.uuid4()),
            "student_user_code": student,
            "purpose": "hostel",
            "amount": "1500.00",
        },
    )


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


def test_push_is_off_unless_explicitly_enabled():
    """A local run must not fire real pushes at students' phones."""
    assert isinstance(get_channel(), NullPushChannel)


def test_a_device_registers_its_push_token():
    response = _client(TENANT_A).post(
        "/api/v1/notify/devices", {"push_token": "ExponentPushToken[abc]"}, format="json"
    )

    assert response.status_code == 200
    device = PushDevice.all_objects.get(push_token="ExponentPushToken[abc]")
    assert device.user_code == "STU-001"
    assert device.is_stale is False


def test_re_registering_the_same_token_does_not_duplicate_it():
    """Re-registering happens on every sign-in — it must stay one row."""
    client = _client(TENANT_A)
    client.post("/api/v1/notify/devices", {"push_token": "tok-1"}, format="json")

    client.post("/api/v1/notify/devices", {"push_token": "tok-1"}, format="json")

    assert PushDevice.all_objects.filter(push_token="tok-1").count() == 1


def test_the_consumer_pushes_to_the_recipients_devices():
    PushDevice.all_objects.create(tenant_id=TENANT_A, user_code="STU-001", push_token="tok-1")

    with patch("notify.push.get_channel") as get:
        get.return_value.send.return_value = []
        dispatch_event(_payment_event(TENANT_A))

    tokens = get.return_value.send.call_args.args[0]
    assert tokens == ["tok-1"]


def test_the_consumer_still_writes_an_inbox_row_when_push_fails():
    PushDevice.all_objects.create(tenant_id=TENANT_A, user_code="STU-001", push_token="tok-1")

    with patch("notify.push.get_channel") as get:
        get.return_value.send.side_effect = Exception("push down")
        dispatch_event(_payment_event(TENANT_A))

    assert Notification.all_objects.filter(user_code="STU-001").exists()


def test_a_token_the_provider_rejects_is_marked_stale():
    PushDevice.all_objects.create(tenant_id=TENANT_A, user_code="STU-001", push_token="tok-dead")

    with patch("notify.push.get_channel") as get:
        get.return_value.send.return_value = ["tok-dead"]
        dispatch_event(_payment_event(TENANT_A))

    assert PushDevice.all_objects.get(push_token="tok-dead").is_stale is True


def test_a_stale_device_is_not_pushed_to_again():
    PushDevice.all_objects.create(
        tenant_id=TENANT_A, user_code="STU-001", push_token="tok-dead", is_stale=True
    )

    with patch("notify.push.get_channel") as get:
        get.return_value.send.return_value = []
        dispatch_event(_payment_event(TENANT_A))

    assert get.return_value.send.call_args.args[0] == []


def test_devices_do_not_leak_across_tenants():
    """Another institution's device must never receive this tenant's push."""
    PushDevice.all_objects.create(
        tenant_id=uuid.uuid4(), user_code="STU-001", push_token="other-tenant"
    )

    with patch("notify.push.get_channel") as get:
        get.return_value.send.return_value = []
        dispatch_event(_payment_event(TENANT_A))

    assert get.return_value.send.call_args.args[0] == []
