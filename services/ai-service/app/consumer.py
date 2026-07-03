"""Grievance event consumer/producer: grievance.created -> grievance.scored.

This is the AI half of the grievance chain. grievance-service publishes
``grievance.created`` (payload ``{ticket_id, raised_by, text}``, ``tenant_id``
at the envelope top level); this module scores the text and publishes
``grievance.scored``.

CRITICAL CROSS-SERVICE CONTRACT — echo ``raised_by``:
    The outgoing ``grievance.scored`` payload carries
    ``{ticket_id, raised_by, sentiment, urgency}``. grievance-service reads
    ticket_id/sentiment/urgency to stamp + auto-escalate the ticket;
    notification-service reads ``raised_by`` to notify the right student. If
    ``raised_by`` is dropped here, the student is never notified. So it is
    echoed straight through from the incoming event.

Event bus wiring is replicated locally (pika + RABBITMQ_URL) instead of importing
suerp_common.events, because that module reads ``django.conf.settings`` and this
is a FastAPI service with no Django. The envelope shape and topic exchange
("suerp.events", routing key = event type) match suerp_common exactly so the
events are interchangeable on the wire.

Idempotency: this service is stateless (no DB), so it cannot dedupe via a
ProcessedEvent table. That is ACCEPTABLE — scoring is deterministic and
grievance-service's ``handle_grievance_scored`` is ``@idempotent``, so a
duplicate ``grievance.scored`` (from at-least-once redelivery) is harmless.

``handle_grievance_created`` is a pure function (event dict -> event dict) so it
is unit-testable without a broker. ``run`` wires pika consume -> handle ->
publish and is the ``python -m app.consumer`` entrypoint.
"""

import json
import logging
import uuid
from datetime import UTC, datetime

import pika
from app.config import settings
from app.sentiment import score

logger = logging.getLogger(__name__)

EXCHANGE = "suerp.events"
DLX = "suerp.events.dlx"

GRIEVANCE_CREATED = "grievance.created"
GRIEVANCE_SCORED = "grievance.scored"

QUEUE = "ai.grievance"


def build_event(type: str, tenant_id: str, payload: dict) -> dict:
    """Build an event envelope matching suerp_common.events.build_event."""
    return {
        "event_id": str(uuid.uuid4()),
        "type": type,
        "tenant_id": str(tenant_id),
        "occurred_at": datetime.now(UTC).isoformat(),
        "payload": payload,
    }


def handle_grievance_created(event: dict) -> dict:
    """Score a ``grievance.created`` event; return a ``grievance.scored`` event.

    Pure function — no broker I/O. Echoes ``raised_by`` from the incoming
    payload (see module docstring: cross-service contract).
    """
    tenant_id = event["tenant_id"]
    payload = event["payload"]
    result = score(payload.get("text", ""))

    return build_event(
        GRIEVANCE_SCORED,
        tenant_id=tenant_id,
        payload={
            "ticket_id": payload["ticket_id"],
            "raised_by": payload.get("raised_by"),  # echoed — do not drop.
            "sentiment": result["sentiment"],
            "urgency": result["urgency"],
        },
    )


def _connect() -> "pika.BlockingConnection":
    return pika.BlockingConnection(pika.URLParameters(settings.RABBITMQ_URL))


def _publish(channel: "pika.channel.Channel", event: dict) -> None:
    """Publish a single event to the topic exchange keyed by its ``type``."""
    channel.basic_publish(
        exchange=EXCHANGE,
        routing_key=event["type"],
        body=json.dumps(event).encode(),
        properties=pika.BasicProperties(
            content_type="application/json",
            delivery_mode=2,  # persistent
            message_id=event["event_id"],
        ),
    )


def run() -> None:  # pragma: no cover - requires a live broker
    """Blocking consume loop: grievance.created -> score -> grievance.scored.

    On success the incoming message is acked; on unhandled exception it is
    nacked without requeue so the broker dead-letters it (matches the
    suerp_common consumer semantics).
    """
    conn = _connect()
    channel = conn.channel()
    channel.exchange_declare(exchange=EXCHANGE, exchange_type="topic", durable=True)
    channel.exchange_declare(exchange=DLX, exchange_type="topic", durable=True)
    channel.queue_declare(
        queue=QUEUE,
        durable=True,
        arguments={"x-dead-letter-exchange": DLX},
    )
    channel.queue_bind(exchange=EXCHANGE, queue=QUEUE, routing_key=GRIEVANCE_CREATED)

    def _on_message(ch, method, properties, body):
        try:
            event = json.loads(body)
            scored = handle_grievance_created(event)
            _publish(ch, scored)
            ch.basic_ack(delivery_tag=method.delivery_tag)
            logger.info(
                "scored ticket_id=%s urgency=%s",
                scored["payload"]["ticket_id"],
                scored["payload"]["urgency"],
            )
        except Exception:
            logger.exception("failed to handle grievance.created; dead-lettering")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    channel.basic_qos(prefetch_count=10)
    channel.basic_consume(queue=QUEUE, on_message_callback=_on_message)
    logger.info("ai-service grievance consumer started; waiting for events")
    channel.start_consuming()


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    run()
