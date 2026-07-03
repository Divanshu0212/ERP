from app.consumer import handle_grievance_created


def test_handle_grievance_created_echoes_raised_by():
    event = {
        "event_id": "evt-123",
        "type": "grievance.created",
        "tenant_id": "tenant-abc",
        "occurred_at": "2026-07-03T00:00:00+00:00",
        "payload": {
            "ticket_id": "ticket-1",
            "raised_by": "student-9",
            "text": "ragging complaint",
        },
    }

    out = handle_grievance_created(event)

    assert out["type"] == "grievance.scored"
    assert out["tenant_id"] == "tenant-abc"
    payload = out["payload"]
    assert payload["ticket_id"] == "ticket-1"
    # CRITICAL cross-service contract: raised_by MUST be echoed through.
    assert payload["raised_by"] == "student-9"
    assert payload["urgency"] == "critical"
    assert isinstance(payload["sentiment"], float)
    # Envelope invariants.
    assert out["event_id"] != event["event_id"]
    assert "occurred_at" in out
