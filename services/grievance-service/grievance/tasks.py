"""Celery tasks for grievance.

``drain_outbox_task`` is wired to Celery Beat (see ``config.settings.
CELERY_BEAT_SCHEDULE``) to periodically relay unpublished ``OutboxEvent`` rows
to RabbitMQ. Mirrors billing/tasks.py in finance-service: one thin task
delegating to ``suerp_common.outbox.drain_outbox``.
"""

from celery import shared_task
from suerp_common.outbox import drain_outbox


@shared_task(name="grievance.tasks.drain_outbox_task")
def drain_outbox_task() -> int:
    return drain_outbox()


@shared_task(name="grievance.tasks.purge_expired_media_task")
def purge_expired_media_task() -> dict:
    """Delete grievance blobs whose retention window has closed.

    Runs on the same beat that drains the outbox. Deleting the file but
    keeping the row is the whole point: the metadata is the audit trail, and
    an already-purged row is skipped, so a repeated sweep is a no-op.

    Uses ``all_objects`` because a beat task runs with no active tenant — the
    sweep is a system operation spanning every institution.
    """
    from django.utils import timezone  # noqa: PLC0415

    from grievance.models import TicketMedia  # noqa: PLC0415

    now = timezone.now()
    expired = TicketMedia.all_objects.filter(
        expires_at__isnull=False, expires_at__lte=now, purged_at__isnull=True
    )

    purged = 0
    for media in expired:
        if media.file:
            media.file.delete(save=False)
        media.purged_at = now
        media.save(update_fields=["file", "purged_at"])
        purged += 1

    return {"purged": purged}
