"""In-app inbox endpoints (Task 5.2).

The inbox is doubly scoped:

1. By tenant — ``Notification.objects`` is auto-filtered to the active tenant
   by ``TenantMiddleware`` (a token for a different tenant sees nothing).
2. By recipient — filtered to the JWT ``sub`` claim
   (``request.user.id``), so user A never sees user B's notifications even
   within the same tenant.

Included under /api/v1/notify/ from config.urls.
"""

from django.shortcuts import get_object_or_404
from notify.models import Notification, PushDevice
from notify.serializers import NotificationSerializer
from rest_framework.generics import ListAPIView
from rest_framework.views import APIView
from suerp_common.envelope import fail, ok
from suerp_common.tenancy import get_current_tenant


class InboxListView(ListAPIView):
    """GET /api/v1/notify/inbox — the current user's notifications.

    Tenant-scoped (via ``objects``) and further filtered to the requesting
    user (JWT ``sub``), newest first, paginated in the standard envelope.
    """

    serializer_class = NotificationSerializer

    def get_queryset(self):
        return Notification.objects.filter(user_code=self.request.user.id).order_by("-created_at")


class MarkReadView(APIView):
    """POST /api/v1/notify/inbox/{id}/read — mark one notification read.

    Scoped to the current tenant AND user, so a user can only ever mark their
    own notifications read; anything else 404s (never visible to them).
    """

    def post(self, request, pk):
        notification = get_object_or_404(
            Notification.objects.filter(user_code=request.user.id), id=pk
        )
        if not notification.read:
            notification.read = True
            notification.save(update_fields=["read"])
        return ok(NotificationSerializer(notification).data, message="Notification marked read.")


class PushDeviceView(APIView):
    """POST /api/v1/notify/devices — register this device for push.

    Upsert on the token rather than create: the app re-registers on every
    sign-in, and a device handed to a new user must follow the new owner
    rather than keep pushing this tenant's notifications to them.
    """

    def post(self, request):
        push_token = (request.data.get("push_token") or "").strip()
        if not push_token:
            return fail("A push token is required.", status=400)

        device, _ = PushDevice.all_objects.update_or_create(
            push_token=push_token,
            defaults={
                "tenant_id": get_current_tenant(),
                "user_code": request.user.id,
                # A token that re-registers is demonstrably alive again.
                "is_stale": False,
            },
        )
        return ok({"id": str(device.id)}, message="Device registered.")
