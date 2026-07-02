import uuid

import pytest
from suerp_common.inbox import ProcessedEvent, idempotent


@pytest.mark.django_db
def test_handler_runs_once_per_event_id():
    calls = {"n": 0}

    @idempotent
    def handler(event):
        calls["n"] += 1

    event = {"event_id": str(uuid.uuid4()), "type": "x", "payload": {}}

    handler(event)
    handler(event)  # duplicate delivery
    handler(event)  # duplicate delivery

    assert calls["n"] == 1
    assert ProcessedEvent.objects.filter(event_id=event["event_id"]).count() == 1


@pytest.mark.django_db
def test_distinct_events_each_run():
    calls = {"n": 0}

    @idempotent
    def handler(event):
        calls["n"] += 1

    handler({"event_id": str(uuid.uuid4()), "payload": {}})
    handler({"event_id": str(uuid.uuid4()), "payload": {}})

    assert calls["n"] == 2
