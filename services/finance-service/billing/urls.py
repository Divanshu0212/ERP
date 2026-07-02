"""Billing endpoints (Task 4.4): invoices and pay.

Included under /api/v1/finance/ from config.urls.
"""

from billing.views import InvoiceListCreateView, PayView
from django.urls import path

urlpatterns = [
    path("invoices", InvoiceListCreateView.as_view(), name="invoice-list-create"),
    path("pay", PayView.as_view(), name="pay"),
]
