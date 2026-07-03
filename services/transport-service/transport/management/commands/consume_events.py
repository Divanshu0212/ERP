"""``manage.py consume_events`` — run transport-service's event consumer loop.

Binds a durable queue (``transport.pass``) to the routing keys this service
cares about and blocks, dispatching each delivered message to its handler.
Intended to run as a long-lived process (one per replica), separate from the
request-serving Django process — mirrors how ``drain_outbox_task`` runs
separately as a Celery beat job, and mirrors
services/hostel-service/hostel/management/commands/consume_events.py.

``transport.consumers.dispatch`` inspects ``event["type"]`` and routes to the
right handler (currently ``finance.payment.success`` -> pass activation).
"""

from django.core.management.base import BaseCommand
from suerp_common.events import make_consumer
from transport.consumers import dispatch


class Command(BaseCommand):
    help = "Consume finance.payment.success and activate transport passes (blocking loop)."

    def handle(self, *args, **options):
        make_consumer(
            queue="transport.pass",
            routing_keys=["finance.payment.success"],
            handler=dispatch,
        )
