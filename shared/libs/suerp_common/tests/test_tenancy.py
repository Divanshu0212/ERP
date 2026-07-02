import uuid

import pytest

from suerp_common.tenancy import get_current_tenant, set_current_tenant


def test_tenant_context_roundtrip():
    tid = str(uuid.uuid4())
    set_current_tenant(tid)
    assert get_current_tenant() == tid
    set_current_tenant(None)
    assert get_current_tenant() is None


@pytest.mark.django_db
def test_tenant_manager_filters_by_current_tenant():
    from tests.testapp.models import Widget

    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())

    Widget.all_objects.create(tenant_id=tenant_a, name="a-widget")
    Widget.all_objects.create(tenant_id=tenant_b, name="b-widget")

    set_current_tenant(tenant_a)
    try:
        names = set(Widget.objects.values_list("name", flat=True))
        assert names == {"a-widget"}
        # all_objects bypasses the tenant filter
        assert Widget.all_objects.count() == 2
    finally:
        set_current_tenant(None)
