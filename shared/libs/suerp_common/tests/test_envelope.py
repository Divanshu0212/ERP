from rest_framework import serializers

from suerp_common.envelope import exception_handler, fail, ok


def test_ok_wraps_data():
    resp = ok({"a": 1}, message="done")
    assert resp.data == {"success": True, "data": {"a": 1}, "message": "done", "errors": None}
    assert resp.status_code == 200


def test_fail_wraps_errors():
    resp = fail("Validation failed", errors={"room_id": ["at capacity"]}, status=400)
    assert resp.data == {
        "success": False,
        "data": None,
        "message": "Validation failed",
        "errors": {"room_id": ["at capacity"]},
    }
    assert resp.status_code == 400


def test_exception_handler_wraps_validation_error():
    exc = serializers.ValidationError({"email": ["This field is required."]})
    resp = exception_handler(exc, context={})
    assert resp is not None
    assert resp.data["success"] is False
    assert resp.data["errors"] == {"email": ["This field is required."]}
    assert resp.status_code == 400
