"""``manage.py consume_events`` — run notification-service's fan-out loop.

Binds a single durable queue (``notification.fanout``) to every routing key
this service reacts to and blocks, dispatching each delivered message to its
handler via ``dispatch_event`` (which routes by ``event["type"]``). Intended
to run as a long-lived process (one per replica), separate from the
request-serving Django process.
"""

from django.core.management.base import BaseCommand
from notify.consumers import dispatch_event
from suerp_common.events import make_consumer

ROUTING_KEYS = [
    "finance.payment.success",
    "hostel.allocation.confirmed",
    "grievance.scored",
]


class Command(BaseCommand):
    help = "Consume finance/hostel/grievance events and fan out inbox notifications."

    def handle(self, *args, **options):
        make_consumer(
            queue="notification.fanout",
            routing_keys=ROUTING_KEYS,
            handler=dispatch_event,
        )
