"""Concurrency proofs for seat allocation — real threads against real Postgres.

Every other test module in this service runs on the SQLite fallback under
``pytest.mark.django_db``, which wraps each test in a single transaction on a
single connection. That setup can never exercise ``select_for_update()``:
SQLite serialises writers anyway, and a wrapping transaction means the
competing "connections" are the same connection. The row-lock in
``hostel.services.create_allocation`` is therefore asserted by its docstring
but never actually proven.

These tests close that gap. They:

  * require PostgreSQL (skipped otherwise — see ``requires_postgres``),
  * use ``TransactionTestCase``, so each thread gets a real, separately
    committed connection rather than sharing one wrapping transaction,
  * run genuine OS threads that contend for the same Room row.

If ``select_for_update()`` were removed from ``create_allocation``, the
last-seat test below fails with over-allocation — that is the whole point.

Run against the compose Postgres — note port 5432, not PgBouncer's 6432: the
test runner has to CREATE DATABASE, which transaction pooling cannot proxy.

    make test-concurrency

    # or directly:
    cd services/hostel-service && \\
      DATABASE_URL=postgres://suerp:suerp@localhost:5432/hostel \\
      JWT_SIGNING_KEY=dev-insecure-change-me \\
      ../../.venv/bin/pytest hostel/tests/test_concurrency.py
"""

import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from django.db import connection, connections
from django.test import TransactionTestCase
from hostel.models import Allocation, Block, Room
from hostel.services import RoomFullError, StudentAlreadyAllocatedError, create_allocation

# These proofs are meaningless on SQLite: it serialises writers, so a passing
# result would say nothing about whether the row-lock works. Skip rather than
# pass vacuously.
requires_postgres = pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="row-lock contention is only meaningful on PostgreSQL; set DATABASE_URL to a Postgres DSN",
)


def _seed_room(tenant_id, capacity, occupied_count=0):
    block = Block.all_objects.create(
        tenant_id=tenant_id, name="Race Block", gender_type="M", warden_id="WARD-1"
    )
    return Room.all_objects.create(
        tenant_id=tenant_id,
        block=block,
        room_no="101",
        capacity=capacity,
        occupied_count=occupied_count,
    )


def _allocate(tenant_id, room_id, student_user_code):
    """Call create_allocation from a worker thread and classify the outcome.

    Django gives each thread its own connection; closing it afterwards keeps
    the test from leaking connections when a thread pool is reused.
    """
    try:
        create_allocation(
            tenant_id=tenant_id,
            room_id=room_id,
            student_user_code=student_user_code,
        )
        return "won"
    except RoomFullError:
        return "rejected"
    except StudentAlreadyAllocatedError:
        return "duplicate"
    finally:
        connections.close_all()


@requires_postgres
class LastSeatRaceTests(TransactionTestCase):
    """N students race for the last free seat. Exactly one may win."""

    def test_fifty_students_race_for_one_seat_exactly_one_wins(self):
        tenant_id = uuid.uuid4()
        # capacity 2, one seat already taken => exactly ONE seat remains
        room = _seed_room(tenant_id, capacity=2, occupied_count=1)
        contenders = 50

        with patch("hostel.services.publish_event"):
            with ThreadPoolExecutor(max_workers=contenders) as pool:
                results = list(
                    pool.map(
                        lambda i: _allocate(tenant_id, room.id, f"race-{i}"),
                        range(contenders),
                    )
                )

        won = results.count("won")
        rejected = results.count("rejected")

        assert won == 1, f"expected exactly 1 winner, got {won} — the room was over-allocated"
        assert (
            rejected == contenders - 1
        ), f"expected {contenders - 1} clean rejections, got {rejected}"

        # the durable state must agree with what the callers were told
        room.refresh_from_db()
        assert room.occupied_count == room.capacity == 2
        assert Allocation.all_objects.filter(tenant_id=tenant_id, room=room).count() == 1

    def test_room_is_never_over_allocated_when_seats_are_contended(self):
        """More contenders than seats: winners must equal free seats, never exceed."""
        tenant_id = uuid.uuid4()
        free_seats = 3
        room = _seed_room(tenant_id, capacity=free_seats, occupied_count=0)
        contenders = 30

        with patch("hostel.services.publish_event"):
            with ThreadPoolExecutor(max_workers=contenders) as pool:
                results = list(
                    pool.map(
                        lambda i: _allocate(tenant_id, room.id, f"multi-{i}"),
                        range(contenders),
                    )
                )

        won = results.count("won")
        assert won == free_seats, f"expected exactly {free_seats} winners, got {won}"

        room.refresh_from_db()
        assert room.occupied_count == free_seats
        assert Allocation.all_objects.filter(tenant_id=tenant_id, room=room).count() == free_seats


@requires_postgres
class DuplicateAllocationRaceTests(TransactionTestCase):
    """The same student firing concurrent requests must not get two seats.

    Guarded by a partial-unique constraint on (tenant_id, student_user_code)
    over active allocations, not by the Room row-lock — a different mechanism
    from the last-seat race above, so it gets its own proof.
    """

    def test_same_student_racing_themselves_gets_exactly_one_allocation(self):
        tenant_id = uuid.uuid4()
        room = _seed_room(tenant_id, capacity=10, occupied_count=0)
        attempts = 20

        with patch("hostel.services.publish_event"):
            with ThreadPoolExecutor(max_workers=attempts) as pool:
                results = list(
                    pool.map(
                        lambda _: _allocate(tenant_id, room.id, "double-clicker"),
                        range(attempts),
                    )
                )

        won = results.count("won")
        assert won == 1, f"student got {won} allocations from {attempts} concurrent requests"

        active = Allocation.all_objects.filter(
            tenant_id=tenant_id,
            student_user_code="double-clicker",
            status__in=[Allocation.Status.PENDING, Allocation.Status.CONFIRMED],
        )
        assert active.count() == 1

        # a double-click must not silently consume extra capacity either
        room.refresh_from_db()
        assert room.occupied_count == 1


@requires_postgres
class CrossTenantRaceTests(TransactionTestCase):
    """Tenant isolation must hold under concurrent load, not just serially."""

    def test_concurrent_tenants_do_not_contend_or_leak(self):
        tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
        room_a = _seed_room(tenant_a, capacity=1)
        room_b = _seed_room(tenant_b, capacity=1)

        with patch("hostel.services.publish_event"):
            with ThreadPoolExecutor(max_workers=20) as pool:
                jobs = []
                for i in range(10):
                    jobs.append(pool.submit(_allocate, tenant_a, room_a.id, f"a-{i}"))
                    jobs.append(pool.submit(_allocate, tenant_b, room_b.id, f"b-{i}"))
                results = [j.result() for j in jobs]

        # one seat per tenant => exactly two winners overall, one on each side
        assert results.count("won") == 2

        for tenant, room in ((tenant_a, room_a), (tenant_b, room_b)):
            allocs = Allocation.all_objects.filter(tenant_id=tenant)
            assert allocs.count() == 1
            assert allocs.first().room_id == room.id
            # no allocation may reference the other tenant's room
            assert not Allocation.all_objects.filter(tenant_id=tenant).exclude(room=room).exists()
