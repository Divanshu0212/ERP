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
from notify.models import Notification
from notify.serializers import NotificationSerializer
from rest_framework.generics import ListAPIView
from rest_framework.views import APIView
from suerp_common.envelope import ok


class InboxListView(ListAPIView):
    """GET /api/v1/notify/inbox — the current user's notifications.

    Tenant-scoped (via ``objects``) and further filtered to the requesting
    user (JWT ``sub``), newest first, paginated in the standard envelope.
    """

    serializer_class = NotificationSerializer

    def get_queryset(self):
        return Notification.objects.filter(user_id=self.request.user.id).order_by("-created_at")


class MarkReadView(APIView):
    """POST /api/v1/notify/inbox/{id}/read — mark one notification read.

    Scoped to the current tenant AND user, so a user can only ever mark their
    own notifications read; anything else 404s (never visible to them).
    """

    def post(self, request, pk):
        notification = get_object_or_404(
            Notification.objects.filter(user_id=request.user.id), id=pk
        )
        if not notification.read:
            notification.read = True
            notification.save(update_fields=["read"])
        return ok(NotificationSerializer(notification).data, message="Notification marked read.")
