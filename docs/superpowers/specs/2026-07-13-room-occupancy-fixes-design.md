# Room occupancy fixes — design

## Problem

Three related gaps in hostel room/allocation management:

1. **Bulk-upload CSV template doesn't reflect room occupancy.** `AvailableRoomsTemplateView`
   writes exactly one row per available room, regardless of `capacity`. A 2-capacity room with
   0 occupants only gets one fillable row, so a warden bulk-uploading can't allocate more than
   one student per room per upload without manually duplicating rows.
2. **No way to adjust room capacity after creation.** `Room.capacity` is set once at
   `POST /api/v1/hostel/rooms` and never editable. Admin has no way to increase or decrease it.
3. **No way for a warden to cancel/release an existing allocation.** The only path that frees a
   room seat (`occupied_count -= 1`, status → `released`) is the automated payment-saga
   (`consumers.py` / `tasks.py` on payment failure or timeout). A warden has no manual override.

## Scope

In scope: the three fixes above, each independent.

Out of scope: student-relocation ("move to a different room") and the two-student room-swap
feature — both fold into the already-documented but unbuilt **Feature 3 (room exchange)** in
the README's "Planned: hostel allocation workflow v2" section. Not touched here.

## Design

### 1. CSV template — one row per free seat

`AvailableRoomsTemplateView.get` (`services/hostel-service/hostel/views.py`) changes from writing
one row per room to writing `capacity - occupied_count` rows per room. Each row for the same room
repeats the same `room_id`/`room_name`, with a blank `student_user_code` slot for the warden to
fill independently. Rooms already at capacity are still excluded entirely (existing
`occupied_count__lt=F("capacity")` filter is unchanged).

No change needed to `AllocateBulkView` — it already processes each CSV row independently via
`create_allocation`, which itself enforces capacity via `RoomFullError`. Multiple rows with the
same `room_id` already work correctly today; the template was just never generating them.

### 2. Admin — edit room capacity

New endpoint: `PATCH /api/v1/hostel/rooms/{id}` (admin only, via `role_required("admin")`).

Body: `{"capacity": <int>}`.

- Rejects with 400 if `capacity < room.occupied_count` — error message: "Capacity cannot be
  lower than current occupancy (N)."
- Otherwise updates `capacity` and returns the updated `RoomSerializer` representation.

Implementation: extend `RoomListCreateView` isn't right (it's list+create only, no detail route)
— add a new `RoomDetailView(APIView)` with `patch`, routed at `rooms/<uuid:pk>`.

Frontend (`admin/page.tsx`): in the "Rooms" table, make the occupancy cell an editable capacity
control (stepper: −/+ buttons, or a small inline number input + save) next to the existing
`occupied_count/capacity` display. Calls the new PATCH endpoint, reloads rooms on success, shows
inline error (e.g. the below-occupancy rejection) via the existing `fieldErrorMessage`/`errMsg`
pattern used elsewhere on this page.

### 3. Warden — release an allocation

New endpoint: `POST /api/v1/hostel/allocations/{id}/release` (warden or admin, via
`role_required("warden", "admin")`).

- 400 if allocation status is already `released`.
- Otherwise: sets `status = Allocation.Status.RELEASED`, decrements `room.occupied_count` by 1
  (same accounting the saga's auto-release path already performs), wrapped in
  `transaction.atomic()`.
- Applies to allocations in `pending` or `confirmed` status (both are "active"; `released` is
  terminal and already excluded by the 400 above).

Frontend (`warden/page.tsx`): the "Pending hostel allocations" panel currently only queries
`?status=pending`. Broaden it to show both `pending` and `confirmed` allocations (two badges via
existing `StatusPill`), and add a "Release" button per row that calls the new endpoint and
reloads the list on success.

## Data flow / error handling

Both new endpoints follow the existing envelope (`ok`/`fail`) and permission (`role_required`)
conventions already used throughout `hostel/views.py`. No new models. No new events published —
these are direct administrative actions, not saga-driven state transitions, so no
`hostel.allocation.*` event needs to fire (nothing downstream currently listens for a manual
release or a capacity change).

## Testing

- CSV template: capacity-many rows per available room; a room already at capacity produces zero
  rows; room_id/room_name repeat correctly across its rows.
- Room capacity PATCH: happy path increases/decreases; rejection when new capacity < occupied_count;
  permission check (non-admin forbidden).
- Allocation release: happy path frees a seat and flips status for both `pending` and `confirmed`
  starting states; 400 on an already-`released` allocation; permission check (student forbidden).
- Existing hostel-service test suite must keep passing (currently 61/61). New tests added
  alongside each fix, following the existing per-view test-file convention.
