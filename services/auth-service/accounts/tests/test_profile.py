"""GET/PATCH /auth/users/me/profile/ and GET /auth/users/{user_code}/profile/ —
common profile fields for every role except superadmin (see UserProfile in
accounts/models.py).
"""

import pytest
from accounts.models import Institution, User, UserProfile
from rest_framework.test import APIClient


@pytest.fixture
def institution(db):
    return Institution.objects.create(slug="profile-test", name="Profile Test U")


@pytest.fixture
def student_user(db, institution):
    return User.objects.create_user(
        tenant=institution,
        email="stu@profiletest.edu",
        password="pw12345678",
        role=User.Role.STUDENT,
        user_code="STU-100",
    )


def _login(client, institution, email, password):
    resp = client.post(
        "/api/v1/auth/login",
        {"institution_slug": institution.slug, "email": email, "password": password},
        format="json",
    )
    return resp.json()["data"]["access"]


def test_get_own_profile_empty_by_default(db, institution, student_user):
    client = APIClient()
    token = _login(client, institution, "stu@profiletest.edu", "pw12345678")
    resp = client.get("/api/v1/auth/users/me/profile/", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert resp.status_code == 200
    assert resp.json()["data"]["phone"] == ""


def test_patch_own_profile(db, institution, student_user):
    client = APIClient()
    token = _login(client, institution, "stu@profiletest.edu", "pw12345678")
    resp = client.patch(
        "/api/v1/auth/users/me/profile/",
        {"phone": "9876543210", "blood_group": "O+"},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["phone"] == "9876543210"
    assert UserProfile.objects.get(pk="STU-100").blood_group == "O+"


def test_superadmin_has_no_profile_endpoint_access(db):
    institution = Institution.objects.create(slug="platform-profile", name="Platform")
    User.objects.create_superuser(
        tenant=institution,
        email="root@platformprofile.edu",
        password="pw12345678",
        role=User.Role.SUPERADMIN,
    )
    client = APIClient()
    token = _login(client, institution, "root@platformprofile.edu", "pw12345678")
    resp = client.get("/api/v1/auth/users/me/profile/", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert resp.status_code == 403


def test_admin_can_view_another_users_profile(db, institution, student_user):
    User.objects.create_user(
        tenant=institution,
        email="admin@profiletest.edu",
        password="pw12345678",
        role=User.Role.ADMIN,
        user_code="ADM-100",
    )
    client = APIClient()
    token = _login(client, institution, "admin@profiletest.edu", "pw12345678")
    resp = client.get(
        f"/api/v1/auth/users/{student_user.user_code}/profile/",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["phone"] == ""


def test_student_cannot_view_another_users_profile(db, institution, student_user):
    other_student = User.objects.create_user(
        tenant=institution,
        email="other@profiletest.edu",
        password="pw12345678",
        role=User.Role.STUDENT,
        user_code="STU-200",
    )
    client = APIClient()
    token = _login(client, institution, "stu@profiletest.edu", "pw12345678")
    resp = client.get(
        f"/api/v1/auth/users/{other_student.user_code}/profile/",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert resp.status_code == 403


def test_requires_authentication(db, institution, student_user):
    client = APIClient()
    resp = client.get("/api/v1/auth/users/me/profile/")
    assert resp.status_code == 401
