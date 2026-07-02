"""Celery tasks for billing.

``drain_outbox_task`` is wired to Celery Beat (see ``config.settings.
CELERY_BEAT_SCHEDULE``) to periodically relay unpublished ``OutboxEvent`` rows
to RabbitMQ. Mirrors accounts/tasks.py in auth-service: one thin task
delegating to ``suerp_common.outbox.drain_outbox``.
"""

from celery import shared_task
from suerp_common.outbox import drain_outbox


@shared_task(name="billing.drain_outbox_task")
def drain_outbox_task() -> int:
    return drain_outbox()
