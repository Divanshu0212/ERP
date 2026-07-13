# Optional-fee allocation, payment due-date expiry, and one-seat-per-student — design

## Problem

1. **Every allocation forces a fee, even when it shouldn't.** `AllocateView`
   (single-add) and `AllocateBulkView` (bulk CSV) never collect a
   `fee_structure_id` at all — only room-request approval does. So every
   single-add/bulk allocation falls through to finance-service's
   `_resolve_hostel_fee_amount` hardcoded default (`HOSTEL_FEE_AMOUNT =
   Decimal("5000.00")`), always creating an invoice and always demanding
   payment, even for allocations that should be free (staff quota,
   scholarship, admin override).
2. **No payment deadline.** Once an invoice exists, nothing ever expires it.
   The only existing timeout is a fixed 30-minute
   `release_stale_pending_allocations` safety net in hostel-service — not
   warden-configurable, and not tied to the invoice/payment concept at all.
3. **No limit on simultaneous allocations per student.** `Allocation` has no
   constraint preventing a student from holding more than one active
   (pending or confirmed) allocation at once, across any room — including
   two rows for the same student in one bulk-CSV upload silently
   double-allocating them.

## Scope

In scope:
- Extend `AllocateView`/`AllocateBulkView` with the same optional
  `fee_structure_id` picker `ApproveRoomRequestView` already has.
- When no fee is selected: skip the invoice/payment saga entirely — the
  allocation confirms immediately.
- When a fee IS selected: a `due_date` becomes mandatory alongside it. The
  invoice must be paid by that date or the allocation is released
  (room seat freed) and shows as failed/expired.
- Replace the fixed 30-minute `PENDING_TIMEOUT` mechanism with a
  due-date-driven check, since every fee-bearing allocation now always
  carries an explicit due date.
- Enforce one active (pending/confirmed) allocation per student across
  any room, at the DB level.

Out of scope: room exchange/swap (Feature 3, still deferred), any change to
the receipt/QR verification flow.

Note: `RoomRequestApproveSerializer.fee_structure_id` is currently
**mandatory** (`serializers.UUIDField()`, no `required=False`) — warden
approval cannot skip the fee today either. This spec makes it optional
too, so all three allocation entry points (single-add, bulk CSV,
room-request approval) get the identical fee_structure_id+due_date-or-
neither rule.

## Design

### 1. Direct/no-fee allocation path

`hostel.allocation.requested` is consumed ONLY by finance-service (verified:
no other service subscribes to it), purely to trigger invoice creation. So
when `fee_structure_id` is omitted, there is nothing for finance-service to
do — `create_allocation()` skips publishing that event entirely and instead
confirms the `Allocation` synchronously, in the same call, same
`transaction.atomic()` block it already holds: status goes straight from
`pending` to `confirmed` (room seat was already reserved by the existing
`occupied_count += 1` a few lines above). No new event type, no new
consumer handler, no round trip through the event bus for something
hostel-service already knows synchronously at creation time. finance-service
never sees this allocation at all — no invoice, no payment, no receipt.

When `fee_structure_id` IS given, behavior is unchanged from today: publish
`hostel.allocation.requested` (now also carrying `due_date`), allocation
stays `pending` until finance-service's existing saga confirms or releases
it.

`HOSTEL_FEE_AMOUNT` constant and its silent-fallback behavior in
`_resolve_hostel_fee_amount` are deleted — a `fee_structure_id` now either
resolves to a real `FeeStructure` or the caller didn't ask for a fee at all;
there is no more "unspecified but still charge something" state.

### 2. Fee-bearing allocation requires a due date

`fee_structure_id` and `due_date` become a package: whenever a caller
supplies `fee_structure_id` (single-add, bulk CSV, or room-request
approval), `due_date` is required in that same request and validated as a
future date. Supplying one without the other is a 400.

`due_date` flows through the existing `hostel.allocation.requested` event
payload (same channel `fee_structure_id`/`university_name` already use) and
is stored in two places, matching the existing `university_name` /
`invoice_id` denormalization pattern (each service needs its own local
copy since there's no cross-service FK):

- **hostel-service**: new `Allocation.due_date` (nullable
  `DateTimeField`) — stamped when the allocation is created with a fee, so
  the periodic release task can check it without calling finance-service.
- **finance-service**: new `Invoice.due_date` (nullable `DateTimeField`) —
  stamped by `handle_allocation_requested` when creating the invoice, so
  the student-facing UI can show "due by \<date\>" and the invoice itself
  carries its own deadline independent of hostel-service.

### 3. Expiry replaces the fixed 30-minute timeout

`hostel/tasks.py`'s `release_stale_pending_allocations` changes from a
fixed `PENDING_TIMEOUT = timedelta(minutes=30)` cutoff to checking each
pending, invoiced allocation's own `Allocation.due_date`:

```python
stale_ids = Allocation.all_objects.filter(
    status=Allocation.Status.PENDING,
    invoice_id__isnull=False,
    due_date__lt=timezone.now(),
).values_list("id", flat=True)
```

Since a fee-bearing allocation always has `due_date` set now (mandatory at
creation), no allocation reaches the payment stage without one — the fixed
30-minute constant and its "premature timeout" guard comments are removed
entirely. No-fee allocations are confirmed immediately (see §1) so they
never enter this queryset in the first place — nothing to time out.

Release semantics are otherwise unchanged from today's implementation: same
`select_for_update()` row-lock pattern, same `PaymentOutcome` guard (never
release an allocation with a recorded payment outcome — handles the
out-of-order event-arrival race), same reuse of `Allocation.Status.RELEASED`
(no new status value — confirmed in brainstorming). The frontend
distinguishes "expired, never paid" from an ordinary manual/failed release
by checking the invoice's own state (`Invoice.status` stays `pending` past
its `due_date` — finance-service doesn't need a new invoice status for
this either; "pending invoice, due_date in the past" is enough for the UI
to render "Payment expired").

### 4. One seat per student (pending or confirmed) across any room

`Allocation` currently has no constraint preventing a student from holding
multiple simultaneous allocations — `create_allocation()` never checks for
an existing active one before creating another. Fix: a new conditional
`UniqueConstraint` on `Allocation`, mirroring the existing
`RoomRequest.roomrequest_one_pending_per_student_room` pattern:

```python
models.UniqueConstraint(
    fields=["tenant_id", "student_user_code"],
    condition=models.Q(status__in=["pending", "confirmed"]),
    name="allocation_one_active_per_student",
)
```

Scoped to `pending`/`confirmed` (not `room` — this is "one seat anywhere,"
not "one seat per room") so a `released` allocation never blocks a later
reallocation for the same student. `create_allocation()` catches the
resulting `IntegrityError` the same way it already catches `RoomFullError`
— a new `StudentAlreadyAllocatedError` raised with a clear message,
handled at each call site (`AllocateView`, `AllocateBulkView` — row marked
failed instead of aborting the batch, same as today's `RoomFullError`/
`LookupFailed` handling — and `ApproveRoomRequestView`). This also closes a
latent bug in bulk CSV upload: a student's `user_code` appearing on two
rows (e.g. copy-paste error) previously double-allocated them silently;
now the second row fails cleanly with this error.

## Data flow

```
Warden allocates (single/bulk/approve)
  |
  |-- no fee_structure_id --> create_allocation() confirms synchronously,
  |                            same transaction, no event published.
  |                            finance-service never involved.
  |
  \-- fee_structure_id + due_date (required together)
        --> hostel.allocation.requested (fee_structure_id, due_date)
              -> hostel: Allocation.due_date stamped at creation
              -> finance: Invoice created with Invoice.due_date, existing saga continues unchanged
                    -> student pays before due_date: existing confirm path, unchanged
                    -> due_date passes unpaid: release_stale_pending_allocations releases it
                       (status -> released, occupied_count -= 1)
```

## Testing

- `AllocateView`/`AllocateBulkView`/`ApproveRoomRequestView`:
  fee_structure_id without due_date (or vice versa) rejected with 400; both
  together succeed and allocation stays `pending`; neither given succeeds
  as a direct allocation with status `confirmed` immediately and no
  `OutboxEvent` of type `hostel.allocation.requested` created.
- finance-service consumer test suite: unaffected by the no-fee path
  (finance-service never receives an event for it); a real
  `fee_structure_id` creates an Invoice with `due_date` stamped from the
  payload; `HOSTEL_FEE_AMOUNT` fallback branch is deleted along with its
  test coverage (replaced by the mandatory-due_date validation tests
  above, which prove the fallback path is now unreachable).
- `release_stale_pending_allocations`: releases a pending+invoiced
  allocation whose `due_date` has passed; does NOT release one whose
  `due_date` is still in the future; does NOT release one with a recorded
  `PaymentOutcome` (existing guard, unchanged); does NOT release a
  no-fee/no-invoice allocation (never enters the queryset — it's already
  `confirmed`).
- `Allocation` unique constraint: a student with an existing `pending` or
  `confirmed` allocation cannot get a second one (single-add, bulk-CSV row,
  or room-request approval all reject with a clear error); a student whose
  prior allocation is `released` CAN get a new one; bulk CSV with the same
  student's user_code on two rows succeeds on the first, fails cleanly on
  the second (batch continues, matching existing per-row failure handling).
- Existing hostel-service (72) and finance-service (40) test suites must
  keep passing; tests that hardcoded the old 30-min-timeout /
  `HOSTEL_FEE_AMOUNT`-fallback behavior are updated to the new due-date
  behavior rather than deleted outright, so the "no fee_structure_id ->
  legacy hardcoded charge" case is provably gone rather than just untested.
