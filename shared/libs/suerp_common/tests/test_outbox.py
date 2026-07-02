import uuid

import pytest
from django.db import transaction
from suerp_common.outbox import OutboxEvent, drain_outbox, publish_event


@pytest.mark.django_db
def test_publish_event_is_rolled_back_with_its_transaction():
    tenant = str(uuid.uuid4())
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            publish_event("user.registered", tenant, {"user_id": "u1"})
            raise RuntimeError("boom")  # force rollback
    # The outbox row must vanish with the rolled-back transaction.
    assert OutboxEvent.objects.count() == 0


@pytest.mark.django_db
def test_publish_event_persists_one_unpublished_row_on_commit():
    tenant = str(uuid.uuid4())
    with transaction.atomic():
        publish_event("user.registered", tenant, {"user_id": "u1"})

    rows = OutboxEvent.objects.all()
    assert rows.count() == 1
    row = rows.first()
    assert row.type == "user.registered"
    assert str(row.tenant_id) == tenant
    assert row.published_at is None


@pytest.mark.django_db
def test_drain_outbox_publishes_and_marks_rows(monkeypatch):
    published = []
    monkeypatch.setattr("suerp_common.outbox.publish_to_broker", lambda ev: published.append(ev))
    tenant = str(uuid.uuid4())
    with transaction.atomic():
        publish_event("finance.payment.success", tenant, {"invoice_id": "i1"})

    count = drain_outbox()
    assert count == 1
    assert published[0]["type"] == "finance.payment.success"
    assert OutboxEvent.objects.filter(published_at__isnull=True).count() == 0
