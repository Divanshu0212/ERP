"""``manage.py consume_events`` — run finance-service's event consumer loop.

Binds a durable queue (``finance.allocation``) to the routing keys this
service cares about and blocks, dispatching each delivered message to its
handler. Intended to run as a long-lived process (one per replica), separate
from the request-serving Django process — mirrors how ``drain_outbox_task``
runs separately as a Celery beat job rather than inline in a view.
"""

from billing.consumers import handle_allocation_requested
from django.core.management.base import BaseCommand
from suerp_common.events import make_consumer


class Command(BaseCommand):
    help = "Consume hostel.allocation.requested and other bound events (blocking loop)."

    def handle(self, *args, **options):
        make_consumer(
            queue="finance.allocation",
            routing_keys=["hostel.allocation.requested"],
            handler=handle_allocation_requested,
        )
