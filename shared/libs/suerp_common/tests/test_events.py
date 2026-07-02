import uuid
from unittest import mock

from suerp_common.events import EXCHANGE, build_event, publish_to_broker


def test_build_event_shape():
    tenant = str(uuid.uuid4())
    ev = build_event("finance.payment.success", tenant, {"invoice_id": "x"})

    assert ev["type"] == "finance.payment.success"
    assert ev["tenant_id"] == tenant
    assert ev["payload"] == {"invoice_id": "x"}
    # event_id is a valid UUID; occurred_at is an ISO-8601 string
    uuid.UUID(ev["event_id"])
    assert "T" in ev["occurred_at"]


def test_publish_to_broker_uses_type_as_routing_key():
    ev = build_event("hostel.allocation.requested", str(uuid.uuid4()), {"room_id": "r1"})

    with mock.patch("suerp_common.events.pika") as pika:
        channel = pika.BlockingConnection.return_value.channel.return_value
        publish_to_broker(ev)

    channel.basic_publish.assert_called_once()
    _, kwargs = channel.basic_publish.call_args
    assert kwargs["exchange"] == EXCHANGE
    assert kwargs["routing_key"] == "hostel.allocation.requested"
