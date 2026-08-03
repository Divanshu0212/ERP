"""Grievance media retention: blobs die 7 days after resolution, metadata lives on.

Tokens come from ``test_create._auth_client`` — this service's existing
helper — so these tests authenticate exactly the way the rest of the suite
does. Setup rows use ``all_objects`` since no tenant is active outside a
request.
"""

import uuid

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from grievance.models import Ticket, TicketMedia
from grievance.tasks import purge_expired_media_task

pytestmark = pytest.mark.django_db

from grievance.tests.test_create import _auth_client  # noqa: E402

TENANT_A = uuid.uuid4()


def _client(tenant_id, role="student", sub="STU-001"):
    return _auth_client(tenant_id, role=role, user_id=sub)


def _ticket(tenant_id, status="open", raised_by="STU-001"):
    return Ticket.all_objects.create(
        tenant_id=tenant_id,
        category="hostel",
        description="Broken fan",
        raised_by=raised_by,
        status=status,
    )


def _upload(client, ticket_id):
    return client.post(
        f"/api/v1/grievance/{ticket_id}/media",
        {"file": SimpleUploadedFile("fan.jpg", b"fake-image-bytes", content_type="image/jpeg")},
        format="multipart",
    )


def test_a_student_attaches_a_photo_to_their_own_ticket():
    ticket = _ticket(TENANT_A)

    response = _upload(_client(TENANT_A), ticket.id)

    assert response.status_code == 201
    assert TicketMedia.all_objects.filter(ticket=ticket).count() == 1
    assert TicketMedia.all_objects.get(ticket=ticket).sha256


def test_another_student_cannot_attach_to_someone_elses_ticket():
    ticket = _ticket(TENANT_A, raised_by="STU-001")

    response = _upload(_client(TENANT_A, sub="STU-002"), ticket.id)

    assert response.status_code == 403


def test_resolving_a_ticket_schedules_its_media_for_purge():
    ticket = _ticket(TENANT_A)
    _upload(_client(TENANT_A), ticket.id)

    warden = _client(TENANT_A, role="warden", sub="WRD-001")
    warden.patch(f"/api/v1/grievance/{ticket.id}/status", {"status": "resolved"}, format="json")

    media = TicketMedia.all_objects.get(ticket=ticket)
    assert media.expires_at is not None
    assert (media.expires_at - timezone.now()).days >= 6


def test_the_sweep_leaves_media_inside_the_grace_window():
    ticket = _ticket(TENANT_A)
    _upload(_client(TENANT_A), ticket.id)
    TicketMedia.all_objects.update(expires_at=timezone.now() + timezone.timedelta(days=3))

    purge_expired_media_task()

    media = TicketMedia.all_objects.get(ticket=ticket)
    assert media.purged_at is None
    assert media.file


def test_the_sweep_deletes_the_blob_but_keeps_the_metadata():
    ticket = _ticket(TENANT_A)
    _upload(_client(TENANT_A), ticket.id)
    original = TicketMedia.all_objects.get(ticket=ticket)
    original_hash = original.sha256
    TicketMedia.all_objects.update(expires_at=timezone.now() - timezone.timedelta(seconds=1))

    purge_expired_media_task()

    media = TicketMedia.all_objects.get(ticket=ticket)
    assert media.purged_at is not None
    assert not media.file
    # The audit trail survives the evidence.
    assert media.sha256 == original_hash
    assert media.captured_at is not None


def test_purging_twice_is_harmless():
    ticket = _ticket(TENANT_A)
    _upload(_client(TENANT_A), ticket.id)
    TicketMedia.all_objects.update(expires_at=timezone.now() - timezone.timedelta(seconds=1))
    purge_expired_media_task()
    first_purge = TicketMedia.all_objects.get(ticket=ticket).purged_at

    purge_expired_media_task()

    assert TicketMedia.all_objects.get(ticket=ticket).purged_at == first_purge


def test_the_media_list_shows_purged_entries_as_metadata():
    ticket = _ticket(TENANT_A)
    _upload(_client(TENANT_A), ticket.id)
    TicketMedia.all_objects.update(expires_at=timezone.now() - timezone.timedelta(seconds=1))
    purge_expired_media_task()

    response = _client(TENANT_A).get(f"/api/v1/grievance/{ticket.id}/media")

    assert response.status_code == 200
    entry = response.json()["data"][0]
    assert entry["purged_at"] is not None
    assert entry["url"] is None
    assert entry["sha256"]


def test_the_ticket_row_reports_its_attachments_and_when_they_were_purged():
    """The log still says "1 attachment, purged on the 9th" after the sweep."""
    ticket = _ticket(TENANT_A)
    _upload(_client(TENANT_A), ticket.id)

    listed = _client(TENANT_A).get("/api/v1/grievance").json()["data"]["results"][0]
    assert listed["media_count"] == 1
    assert listed["media_purged_at"] is None

    TicketMedia.all_objects.update(expires_at=timezone.now() - timezone.timedelta(seconds=1))
    purge_expired_media_task()

    listed = _client(TENANT_A).get("/api/v1/grievance").json()["data"]["results"][0]
    assert listed["media_count"] == 1
    assert listed["media_purged_at"] is not None


def test_media_does_not_leak_across_tenants():
    """A ticket from another institution is not found, let alone readable."""
    ticket = _ticket(TENANT_A)
    _upload(_client(TENANT_A), ticket.id)

    response = _client(uuid.uuid4(), sub="STU-001").get(f"/api/v1/grievance/{ticket.id}/media")

    assert response.status_code == 404
