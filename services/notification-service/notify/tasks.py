"""Celery tasks for notify.

``drain_outbox_task`` is wired to Celery Beat (see ``config.settings.
CELERY_BEAT_SCHEDULE``) for template parity with the other services. This
service is a terminal consumer and does not itself publish events, so its
outbox is normally empty; the task delegates to ``suerp_common.outbox.
drain_outbox`` regardless so any future outbound events are relayed safely.
"""

from celery import shared_task
from suerp_common.outbox import drain_outbox


@shared_task(name="notify.drain_outbox_task")
def drain_outbox_task() -> int:
    return drain_outbox()
