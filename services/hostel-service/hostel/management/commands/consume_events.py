"""``manage.py consume_events`` — run hostel-service's event consumer loop.

Binds a durable queue (``hostel.allocation.saga``) to the routing keys this
service cares about and blocks, dispatching each delivered message to its
handler. Intended to run as a long-lived process (one per replica), separate
from the request-serving Django process — mirrors how ``drain_outbox_task``
runs separately as a Celery beat job rather than inline in a view, and
mirrors services/finance-service/billing/management/commands/consume_events.py.

Unlike finance-service (single routing key -> single handler),
hostel-service needs to react to three related events on the SAME queue
(``finance.invoice.created``, ``finance.payment.success``,
``finance.payment.failed`` — see hostel/consumers.py for why), and
``make_consumer`` takes exactly one handler. ``hostel.consumers.dispatch``
is the small fan-out function that inspects ``event["type"]`` and routes to
the right handler.
"""

from django.core.management.base import BaseCommand
from hostel.consumers import dispatch
from suerp_common.events import make_consumer


class Command(BaseCommand):
    help = (
        "Consume finance.invoice.created / finance.payment.success / "
        "finance.payment.failed (blocking loop)."
    )

    def handle(self, *args, **options):
        make_consumer(
            queue="hostel.allocation.saga",
            routing_keys=[
                "finance.invoice.created",
                "finance.payment.success",
                "finance.payment.failed",
            ],
            handler=dispatch,
        )
