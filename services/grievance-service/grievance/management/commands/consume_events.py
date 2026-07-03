"""``manage.py consume_events`` — run grievance-service's event consumer loop.

Binds a durable queue (``grievance.scoring``) to the routing keys this service
cares about and blocks, dispatching each delivered message to its handler.
Intended to run as a long-lived process (one per replica), separate from the
request-serving Django process — mirrors how ``drain_outbox_task`` runs
separately as a Celery beat job, and mirrors
services/transport-service/transport/management/commands/consume_events.py.

``grievance.consumers.dispatch`` inspects ``event["type"]`` and routes to the
right handler (currently ``grievance.scored`` -> apply scoring + auto-escalate).
"""

from django.core.management.base import BaseCommand
from grievance.consumers import dispatch
from suerp_common.events import make_consumer


class Command(BaseCommand):
    help = "Consume grievance.scored and apply sentiment/urgency + auto-escalation (blocking loop)."

    def handle(self, *args, **options):
        make_consumer(
            queue="grievance.scoring",
            routing_keys=["grievance.scored"],
            handler=dispatch,
        )
