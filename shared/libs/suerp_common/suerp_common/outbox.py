"""Transactional outbox.

``publish_event`` records the event in the same database transaction as the
state change that produced it — so an event is never lost if the broker is down
or the process dies between commit and publish. A periodic ``drain_outbox``
(wired to Celery beat per service) relays unpublished rows to RabbitMQ,
guaranteeing at-least-once delivery.
"""

import uuid

from django.db import connection, models, transaction

from .events import build_event, publish_to_broker


class OutboxEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.CharField(max_length=100, db_index=True)
    tenant_id = models.UUIDField()
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        app_label = "suerp_common"
        indexes = [models.Index(fields=["published_at", "created_at"])]

    def as_event(self) -> dict:
        return {
            "event_id": str(self.id),
            "type": self.type,
            "tenant_id": str(self.tenant_id),
            "occurred_at": self.created_at.isoformat() if self.created_at else None,
            "payload": self.payload,
        }


def publish_event(type: str, tenant_id: str, payload: dict) -> OutboxEvent:
    """Enqueue an event for reliable delivery.

    MUST be called inside the caller's ``transaction.atomic()`` so the event and
    the state change commit or roll back together.
    """
    event = build_event(type, tenant_id, payload)
    return OutboxEvent.objects.create(
        id=event["event_id"],
        type=type,
        tenant_id=tenant_id,
        payload=payload,
    )


def drain_outbox(batch: int = 100) -> int:
    """Publish up to ``batch`` unpublished events; return the number published.

    Rows are locked ``FOR UPDATE SKIP LOCKED`` on Postgres so multiple drainers
    (e.g. several service replicas) never publish the same event twice.
    """
    supports_skip_locked = connection.vendor == "postgresql"
    published = 0
    with transaction.atomic():
        qs = OutboxEvent.objects.filter(published_at__isnull=True).order_by("created_at")
        if supports_skip_locked:
            qs = qs.select_for_update(skip_locked=True)
        rows = list(qs[:batch])
        for row in rows:
            publish_to_broker(row.as_event())
            published += 1
        if rows:
            ids = [r.id for r in rows]
            OutboxEvent.objects.filter(id__in=ids).update(published_at=models.functions.Now())
    return published
