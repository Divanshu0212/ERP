"""Inbox endpoints (Task 5.2): list and mark-read.

Included under /api/v1/notify/ from config.urls.
"""

from django.urls import path
from notify.views import InboxListView, MarkReadView

urlpatterns = [
    path("inbox", InboxListView.as_view(), name="inbox-list"),
    path("inbox/<uuid:pk>/read", MarkReadView.as_view(), name="inbox-mark-read"),
]
