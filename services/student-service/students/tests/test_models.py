"""StudentProfile model constraints."""

import uuid

import pytest
from django.db import IntegrityError, transaction
from students.models import StudentProfile

pytestmark = pytest.mark.django_db


def test_user_code_unique_per_tenant():
    tenant_id = uuid.uuid4()
    StudentProfile.objects.create(
        tenant_id=tenant_id, user_code="STU-1", department="CS", batch="2026", semester=1
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            StudentProfile.objects.create(
                tenant_id=tenant_id, user_code="STU-1", department="EE", batch="2026", semester=1
            )


def test_same_user_code_allowed_across_different_tenants():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    StudentProfile.objects.create(
        tenant_id=tenant_a, user_code="STU-1", department="CS", batch="2026", semester=1
    )
    # No exception: user_code uniqueness is per-tenant, not global.
    StudentProfile.objects.create(
        tenant_id=tenant_b, user_code="STU-1", department="CS", batch="2026", semester=1
    )
