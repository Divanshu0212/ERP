"""Seat-availability caching helpers.

Available seats for a BusSchedule = ``capacity - count(booked bookings)``.
Counting live bookings on every read doesn't scale for a hot schedule, so the
count is cached in Redis (via Django's cache framework — see
``config.settings.CACHES``) under a TENANT-NAMESPACED key with a short TTL.

Invalidation is by DELETE, not decrement: on a successful booking the view
calls ``invalidate_seats`` which drops the key, and the next read recomputes
from the DB and re-caches. Deletion is simpler and less bug-prone than
maintaining a live counter (no drift, no negative-count races), and the short
TTL bounds staleness for any path that mutates bookings without invalidating.
"""

from django.core.cache import cache

from .models import Booking, BusSchedule

SEATS_TTL_SECONDS = 30


def seats_cache_key(tenant_id, schedule_id) -> str:
    """Tenant-namespaced cache key so no tenant can read another's seat count."""
    return f"seats:{tenant_id}:{schedule_id}"


def _compute_available(schedule: BusSchedule) -> int:
    booked = Booking.all_objects.filter(
        tenant_id=schedule.tenant_id,
        schedule=schedule,
        status=Booking.Status.BOOKED,
    ).count()
    return max(0, schedule.capacity - booked)


def get_available_seats(schedule: BusSchedule) -> int:
    """Return available seats for ``schedule``, using the cache when warm.

    Cache miss -> compute from the DB and set with a short TTL. The key is
    tenant-namespaced by ``schedule.tenant_id``.
    """
    key = seats_cache_key(schedule.tenant_id, schedule.id)
    cached = cache.get(key)
    if cached is not None:
        return cached
    available = _compute_available(schedule)
    cache.set(key, available, SEATS_TTL_SECONDS)
    return available


def invalidate_seats(tenant_id, schedule_id) -> None:
    """Drop the cached seat count so the next read recomputes from the DB."""
    cache.delete(seats_cache_key(tenant_id, schedule_id))
