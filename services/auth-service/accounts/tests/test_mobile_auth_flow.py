"""Mobile login/refresh/logout over device-bound rotation chains.

The web app's stateless flow must keep working unchanged — see the
backward-compatibility tests at the bottom.
"""

import pytest
from accounts.models import Device, Institution, RefreshTokenRecord, User
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

PASSWORD = "s3cur3-passw0rd"


@pytest.fixture
def client():
    return APIClient()


def _institution(slug="alpha"):
    return Institution.objects.create(slug=slug, name=f"{slug} University")


def _user(institution, email="student@example.com", user_code="STU-001"):
    return User.objects.create_user(
        tenant=institution,
        email=email,
        password=PASSWORD,
        user_code=user_code,
        role=User.Role.STUDENT,
    )


def _login(client, institution, device_id="dev-1", email="student@example.com"):
    payload = {"institution_slug": institution.slug, "email": email, "password": PASSWORD}
    if device_id is not None:
        payload |= {"device_id": device_id, "platform": "android", "model_name": "Pixel 7"}
    return client.post("/api/v1/auth/login", payload, format="json")


def test_login_with_device_registers_it_and_records_the_refresh_token(client):
    inst = _institution()
    _user(inst)

    response = _login(client, inst)

    assert response.status_code == 200
    assert Device.objects.filter(device_id="dev-1").count() == 1
    assert RefreshTokenRecord.objects.count() == 1


def test_refresh_rotates_and_returns_a_new_refresh_token(client):
    inst = _institution()
    _user(inst)
    first = _login(client, inst).json()["data"]

    response = client.post("/api/v1/auth/refresh", {"refresh": first["refresh"]}, format="json")

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["refresh"] != first["refresh"]
    assert body["access"]


def test_reusing_a_rotated_refresh_token_is_rejected_with_401(client):
    inst = _institution()
    _user(inst)
    first = _login(client, inst).json()["data"]
    client.post("/api/v1/auth/refresh", {"refresh": first["refresh"]}, format="json")

    response = client.post("/api/v1/auth/refresh", {"refresh": first["refresh"]}, format="json")

    assert response.status_code == 401
    assert RefreshTokenRecord.objects.filter(revoked_at__isnull=True).count() == 0


def test_logout_revokes_the_chain_so_refresh_stops_working(client):
    inst = _institution()
    _user(inst)
    tokens = _login(client, inst).json()["data"]

    logout = client.post("/api/v1/auth/logout", {"refresh": tokens["refresh"]}, format="json")
    assert logout.status_code == 200

    response = client.post("/api/v1/auth/refresh", {"refresh": tokens["refresh"]}, format="json")
    assert response.status_code == 401


def test_logout_leaves_other_devices_alone(client):
    inst = _institution()
    _user(inst)
    phone = _login(client, inst, device_id="dev-phone").json()["data"]
    tablet = _login(client, inst, device_id="dev-tablet").json()["data"]

    client.post("/api/v1/auth/logout", {"refresh": phone["refresh"]}, format="json")

    response = client.post("/api/v1/auth/refresh", {"refresh": tablet["refresh"]}, format="json")
    assert response.status_code == 200


def test_web_login_without_device_fields_still_works(client):
    inst = _institution()
    _user(inst)

    response = _login(client, inst, device_id=None)

    assert response.status_code == 200
    assert response.json()["data"]["access"]
    assert Device.objects.count() == 0


def test_web_refresh_of_an_untracked_token_still_works(client):
    inst = _institution()
    _user(inst)
    tokens = _login(client, inst, device_id=None).json()["data"]

    response = client.post("/api/v1/auth/refresh", {"refresh": tokens["refresh"]}, format="json")

    assert response.status_code == 200
    assert response.json()["data"]["access"]
