"""Idempotent event consumption.

Because the transactional outbox guarantees *at-least-once* delivery, consumers
must tolerate duplicates. The ``idempotent`` decorator records each handled
``event_id`` in ``ProcessedEvent`` and short-circuits repeat deliveries, so
event handlers can be written as if they run exactly once.
"""

import functools
from collections.abc import Callable

from django.db import IntegrityError, models, transaction


class ProcessedEvent(models.Model):
    event_id = models.UUIDField(primary_key=True)
    processed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "suerp_common"


def idempotent(handler: Callable[[dict], None]) -> Callable[[dict], None]:
    """Wrap an event handler so each ``event_id`` is processed at most once.

    The handler body and the ``ProcessedEvent`` insert run in one transaction;
    if the insert races with a concurrent delivery, the ``IntegrityError`` on the
    unique PK means another worker already handled it and we skip silently.
    """

    @functools.wraps(handler)
    def wrapper(event: dict) -> None:
        event_id = event["event_id"]
        if ProcessedEvent.objects.filter(event_id=event_id).exists():
            return
        try:
            with transaction.atomic():
                ProcessedEvent.objects.create(event_id=event_id)
                handler(event)
        except IntegrityError:
            # Concurrent delivery already recorded this event_id — safe to skip.
            return

    return wrapper
