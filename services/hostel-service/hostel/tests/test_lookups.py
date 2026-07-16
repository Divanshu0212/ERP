"""hostel/lookups.py — the platform's first synchronous inter-service call.

Mocks ``requests.get`` directly rather than hitting a real auth-service, since
this is a unit test of the HTTP-calling logic (status/timeout/parse handling),
not an integration test of auth-service itself.
"""

from unittest.mock import Mock, patch

import pytest
import requests
from hostel.lookups import LookupFailed, resolve_user_by_code


def _response(status_code, json_body=None):
    resp = Mock()
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    resp.json.return_value = json_body or {}
    return resp


@patch("hostel.lookups.requests.get")
def test_resolves_code_on_success(mock_get):
    mock_get.return_value = _response(
        200,
        {"success": True, "data": {"user_code": "u1", "email": "a@example.com", "role": "student"}},
    )

    result = resolve_user_by_code("u1", "Bearer tok")

    assert result == {"user_code": "u1", "email": "a@example.com", "role": "student"}
    called_url, called_kwargs = mock_get.call_args
    assert called_kwargs["params"] == {"user_code": "u1"}
    assert called_kwargs["headers"] == {"Authorization": "Bearer tok"}
    assert called_kwargs["timeout"] == 5


@patch("hostel.lookups.requests.get")
def test_raises_not_found_on_404(mock_get):
    mock_get.return_value = _response(404)

    with pytest.raises(LookupFailed) as exc_info:
        resolve_user_by_code("nobody", "Bearer tok")

    assert exc_info.value.reason == "not_found"


@patch("hostel.lookups.requests.get")
def test_raises_unavailable_on_non_2xx(mock_get):
    mock_get.return_value = _response(500)

    with pytest.raises(LookupFailed) as exc_info:
        resolve_user_by_code("u1", "Bearer tok")

    assert exc_info.value.reason == "unavailable"


@patch("hostel.lookups.requests.get")
def test_raises_unavailable_on_timeout(mock_get):
    mock_get.side_effect = requests.Timeout("timed out")

    with pytest.raises(LookupFailed) as exc_info:
        resolve_user_by_code("u1", "Bearer tok")

    assert exc_info.value.reason == "unavailable"


@patch("hostel.lookups.requests.get")
def test_works_without_auth_header(mock_get):
    mock_get.return_value = _response(
        200,
        {"success": True, "data": {"user_code": "u1", "email": "a@example.com", "role": "student"}},
    )

    resolve_user_by_code("u1", None)

    assert mock_get.call_args.kwargs["headers"] == {}
