"""``manage.py consume_events`` — run student-service's event consumer loop.

Binds a durable queue (``student.profile.sync``) to ``user.registered`` and
blocks, dispatching each delivered message to ``students.consumers.dispatch``.
Intended to run as a long-lived process, separate from the request-serving
Django process — mirrors
services/hostel-service/hostel/management/commands/consume_events.py.
"""

from django.core.management.base import BaseCommand
from students.consumers import dispatch
from suerp_common.events import make_consumer


class Command(BaseCommand):
    help = "Consume user.registered and create matching StudentProfile rows (blocking loop)."

    def handle(self, *args, **options):
        make_consumer(
            queue="student.profile.sync",
            routing_keys=["user.registered"],
            handler=dispatch,
        )
