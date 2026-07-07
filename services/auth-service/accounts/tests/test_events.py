"""Task 3.4: user.registered outbox event + celery-beat drain.

Covers the transactional-outbox guarantee for registration (event and user
commit/rollback together) and the Celery Beat task that drains the outbox to
the broker.
"""

import pytest
from accounts.models import Institution, User
from accounts.tasks import drain_outbox_task
from rest_framework.test import APIClient
from suerp_common.outbox import OutboxEvent

pytestmark = pytest.mark.django_db


def _make_institution(slug="alpha", name="Alpha University", is_active=True):
    return Institution.objects.create(slug=slug, name=name, is_active=is_active)


@pytest.fixture
def client():
    return APIClient()


def _register(
    client,
    institution,
    email="student@example.com",
    password="s3cur3-passw0rd",
    role=None,
    user_code="STU-001",
):
    payload = {
        "institution_slug": institution.slug,
        "email": email,
        "password": password,
        "user_code": user_code,
    }
    if role is not None:
        payload["role"] = role
    return client.post("/api/v1/auth/register", payload, format="json")


def test_register_emits_exactly_one_unpublished_user_registered_event(client):
    inst = _make_institution()

    response = _register(client, inst)

    assert response.status_code == 201
    user = User.objects.get(tenant=inst, email="student@example.com")

    events = OutboxEvent.objects.filter(type="user.registered")
    assert events.count() == 1
    event = events.first()
    assert event.published_at is None
    assert str(event.tenant_id) == str(inst.id)
    assert event.payload["user_code"] == user.user_code
    assert event.payload["role"] == user.role


def test_register_rolls_back_user_and_event_together_when_publish_fails(client, monkeypatch):
    inst = _make_institution()
    monkeypatch.setattr(
        "accounts.views.publish_event",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("broker exploded")),
    )

    client.raise_request_exception = False
    response = _register(client, inst)

    assert response.status_code >= 400
    assert not User.objects.filter(tenant=inst, email="student@example.com").exists()
    assert OutboxEvent.objects.filter(type="user.registered").count() == 0


def test_drain_outbox_task_publishes_registered_event_and_marks_it(client, monkeypatch):
    published = []
    monkeypatch.setattr("suerp_common.outbox.publish_to_broker", lambda ev: published.append(ev))

    inst = _make_institution()
    _register(client, inst)
    assert OutboxEvent.objects.filter(published_at__isnull=True).count() == 1

    count = drain_outbox_task()

    assert count == 1
    assert published[0]["type"] == "user.registered"
    assert OutboxEvent.objects.filter(published_at__isnull=True).count() == 0
