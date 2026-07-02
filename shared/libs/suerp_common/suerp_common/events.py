"""Event bus primitives — envelope builder and RabbitMQ publish/consume.

Events flow through a single topic exchange ``suerp.events``; the routing key is
the event ``type`` (e.g. ``finance.payment.success``). Consumers bind a queue to
the routing keys they care about. Poison messages are dead-lettered.
"""

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import pika
from django.conf import settings

EXCHANGE = "suerp.events"
DLX = "suerp.events.dlx"


def build_event(type: str, tenant_id: str, payload: dict) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "type": type,
        "tenant_id": str(tenant_id),
        "occurred_at": datetime.now(UTC).isoformat(),
        "payload": payload,
    }


def _connect() -> "pika.BlockingConnection":
    url = getattr(settings, "RABBITMQ_URL", None) or "amqp://guest:guest@localhost:5672/"
    return pika.BlockingConnection(pika.URLParameters(url))


def publish_to_broker(event: dict) -> None:
    """Publish a single event to the topic exchange keyed by its ``type``."""
    conn = _connect()
    try:
        channel = conn.channel()
        channel.exchange_declare(exchange=EXCHANGE, exchange_type="topic", durable=True)
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
    finally:
        conn.close()


def make_consumer(
    queue: str,
    routing_keys: list[str],
    handler: Callable[[dict], None],
) -> None:
    """Blocking consumer loop: dispatch each message to ``handler``.

    On success the message is acked; on unhandled exception it is nacked without
    requeue so the broker routes it to the dead-letter exchange for inspection.
    """
    conn = _connect()
    channel = conn.channel()
    channel.exchange_declare(exchange=EXCHANGE, exchange_type="topic", durable=True)
    channel.exchange_declare(exchange=DLX, exchange_type="topic", durable=True)
    channel.queue_declare(
        queue=queue,
        durable=True,
        arguments={"x-dead-letter-exchange": DLX},
    )
    for rk in routing_keys:
        channel.queue_bind(exchange=EXCHANGE, queue=queue, routing_key=rk)

    def _on_message(ch, method, properties, body):
        try:
            event = json.loads(body)
            handler(event)
            ch.basic_ack(delivery_tag=method.delivery_tag)
        except Exception:
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    channel.basic_qos(prefetch_count=10)
    channel.basic_consume(queue=queue, on_message_callback=_on_message)
    channel.start_consuming()
