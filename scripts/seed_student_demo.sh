#!/usr/bin/env bash
# Seeds demo data for the mobile student surface: canteen menu, invoices,
# notifications, a hostel block/room/allocation, and a bus route with a
# schedule. Idempotent — safe to run repeatedly.
#
# Usage: scripts/seed_student_demo.sh [student_user_code]
# Requires the default compose profile to be up (see docs/RUNBOOK-mobile.md).

set -euo pipefail

STUDENT="${1:-MOB-TEST-001}"
TENANT="$(docker exec auth-service python -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
django.setup()
from accounts.models import Institution
print(Institution.objects.get(slug='iiitdmj').id)
" 2>/dev/null | tr -d '\r')"

echo "Seeding for student=$STUDENT tenant=$TENANT"

echo "--- canteen menu ---"
docker exec canteen-service python -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
django.setup()
from canteen.models import MenuItem
items = [
    ('Masala Dosa', '60.00', True),
    ('Veg Thali', '90.00', True),
    ('Paneer Roll', '75.00', True),
    ('Cold Coffee', '45.00', True),
    ('Samosa (2 pcs)', '30.00', True),
    ('Gulab Jamun', '35.00', False),
]
for name, price, available in items:
    MenuItem.all_objects.get_or_create(
        tenant_id='$TENANT', name=name,
        defaults=dict(price=price, available=available),
    )
print('menu items:', MenuItem.all_objects.filter(tenant_id='$TENANT').count())
"

echo "--- finance invoices ---"
docker exec finance-service python -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
django.setup()
import uuid
from billing.models import Invoice, Payment, Receipt
from billing.receipts import generate_receipt
from suerp_common.tenancy import set_current_tenant

set_current_tenant('$TENANT')

rows = [
    ('Hostel fee - Autumn 2026', '45000.00', 'pending'),
    ('Mess advance - August', '6500.00', 'pending'),
    ('Tuition fee - Autumn 2026', '125000.00', 'paid'),
    ('Library fine', '250.00', 'paid'),
]
for purpose, amount, status in rows:
    invoice, _ = Invoice.all_objects.get_or_create(
        tenant_id='$TENANT', student_user_code='$STUDENT', purpose=purpose,
        defaults=dict(amount=amount, status=status),
    )
    # A paid invoice needs a Payment and a Receipt behind it, or the app's
    # 'View receipt' button 404s. Flipping status alone is not enough.
    if status == 'paid' and not Payment.all_objects.filter(invoice=invoice).exists():
        payment = Payment.all_objects.create(
            tenant_id='$TENANT', invoice=invoice, amount=invoice.amount,
            status='success', idempotency_key=str(uuid.uuid4()),
            gateway_ref=f'SEED-{uuid.uuid4().hex[:10]}',
        )
        try:
            generate_receipt(payment)
        except Exception as exc:
            print('  receipt skipped for', purpose, '-', exc)

print('invoices:', Invoice.all_objects.filter(tenant_id='$TENANT', student_user_code='$STUDENT').count())
print('receipts:', Receipt.all_objects.filter(tenant_id='$TENANT').count())
"

echo "--- notifications ---"
docker exec notification-service python -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
django.setup()
from notify.models import Notification
rows = [
    ('Hostel fee due 15 August', 'Pay your hostel fee before 15 August to keep your room allocation.', False),
    ('Mess menu updated', 'The autumn mess menu is now live in the canteen tab.', False),
    ('Bus route 2 timing changed', 'The 8:15 AM departure now leaves at 8:30 AM from the main gate.', False),
    ('Library books due', 'Two borrowed books are due this Friday.', True),
]
for title, body, read in rows:
    Notification.all_objects.get_or_create(
        tenant_id='$TENANT', user_code='$STUDENT', title=title,
        defaults=dict(body=body, read=read),
    )
print('notifications:', Notification.all_objects.filter(tenant_id='$TENANT').count())
"

echo "--- hostel block, rooms, allocation ---"
docker exec hostel-service python -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
django.setup()
from hostel.models import Allocation, Block, Room
block, _ = Block.all_objects.get_or_create(
    tenant_id='$TENANT', name='Nehru Block',
    defaults=dict(gender_type='M', warden_id='WARD-001'),
)
rooms = {}
for room_no, capacity, occupied in [('A-101', 3, 1), ('A-102', 2, 0), ('A-103', 3, 2), ('B-201', 2, 0)]:
    room, _ = Room.all_objects.get_or_create(
        tenant_id='$TENANT', block=block, room_no=room_no,
        defaults=dict(capacity=capacity, occupied_count=occupied),
    )
    rooms[room_no] = room
Allocation.all_objects.get_or_create(
    tenant_id='$TENANT', student_user_code='$STUDENT', room=rooms['A-101'],
    defaults=dict(status='confirmed'),
)
print('rooms:', Room.all_objects.filter(tenant_id='$TENANT').count())
print('allocations:', Allocation.all_objects.filter(tenant_id='$TENANT').count())
"

echo "--- transport routes and schedules ---"
docker exec transport-service python -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
django.setup()
from datetime import timedelta
from django.utils import timezone
from transport.models import Booking, BusSchedule, Route
now = timezone.now()
data = [
    ('Route 1 - Campus to Railway Station', 'Campus', 'Railway Station', [('MP20-1234', 2), ('MP20-1235', 5)]),
    ('Route 2 - Campus to City Mall', 'Campus', 'City Mall', [('MP20-2234', 3)]),
]
for name, start, end, buses in data:
    route, _ = Route.all_objects.get_or_create(
        tenant_id='$TENANT', name=name,
        defaults=dict(start_point=start, end_point=end),
    )
    for bus_no, hours in buses:
        schedule, created = BusSchedule.all_objects.get_or_create(
            tenant_id='$TENANT', route=route, bus_no=bus_no,
            defaults=dict(driver_id='DRV-001', departure_time=now + timedelta(hours=hours), capacity=32),
        )
        if created:
            # A few seats already gone, so the picker shows both states.
            for seat_no in (1, 2, 7):
                Booking.all_objects.get_or_create(
                    tenant_id='$TENANT', schedule=schedule, seat_no=seat_no,
                    defaults=dict(student_user_code='STU-OTHER', status='booked'),
                )
print('routes:', Route.all_objects.filter(tenant_id='$TENANT').count())
print('schedules:', BusSchedule.all_objects.filter(tenant_id='$TENANT').count())
"

echo "--- grievance tickets ---"
docker exec grievance-service python -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
django.setup()
from grievance.models import Ticket
rows = [
    ('hostel', 'Ceiling fan in A-101 stopped working two days ago.', 'in_progress', 'medium'),
    ('it', 'Wifi keeps dropping in the reading room after 9 PM.', 'open', 'low'),
]
for category, description, status, urgency in rows:
    Ticket.all_objects.get_or_create(
        tenant_id='$TENANT', raised_by='$STUDENT', description=description,
        defaults=dict(category=category, status=status, urgency=urgency),
    )
print('tickets:', Ticket.all_objects.filter(tenant_id='$TENANT').count())
"

echo
echo "Done. Sign in as mobile.test@iiitdmj.ac.in (institution: iiitdmj)."
