import uuid

from suerp_common.auth import SimpleUser
from suerp_common.permissions import IsObjectOwner, TenantRequired, role_required
from suerp_common.tenancy import set_current_tenant


class _Req:
    def __init__(self, user):
        self.user = user


class _Obj:
    def __init__(self, owner_id):
        self.owner_id = owner_id


def _user(role="student", uid=None):
    return SimpleUser(user_id=uid or str(uuid.uuid4()), role=role, tenant_id=str(uuid.uuid4()))


def test_role_required_allows_listed_role_and_denies_others():
    perm = role_required("warden")()
    assert perm.has_permission(_Req(_user(role="warden")), view=None) is True
    assert perm.has_permission(_Req(_user(role="student")), view=None) is False


def test_tenant_required_denies_when_no_tenant():
    perm = TenantRequired()
    set_current_tenant(None)
    assert perm.has_permission(_Req(_user()), view=None) is False
    set_current_tenant(str(uuid.uuid4()))
    try:
        assert perm.has_permission(_Req(_user()), view=None) is True
    finally:
        set_current_tenant(None)


def test_object_owner_allows_owner_and_admin_denies_stranger():
    perm = IsObjectOwner()
    uid = str(uuid.uuid4())
    owner = _user(uid=uid)
    obj = _Obj(owner_id=uid)
    assert perm.has_object_permission(_Req(owner), view=None, obj=obj) is True

    stranger = _user(uid=str(uuid.uuid4()))
    assert perm.has_object_permission(_Req(stranger), view=None, obj=obj) is False

    admin = _user(role="admin", uid=str(uuid.uuid4()))
    assert perm.has_object_permission(_Req(admin), view=None, obj=obj) is True
