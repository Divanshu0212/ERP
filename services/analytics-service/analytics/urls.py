"""Analytics endpoints, included under /api/v1/metrics/ from config.urls."""

from analytics.views import MetricSnapshotListCreateView
from django.urls import path

urlpatterns = [
    path("", MetricSnapshotListCreateView.as_view(), name="metric-list-create"),
]
