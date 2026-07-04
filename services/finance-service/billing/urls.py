"""Billing endpoints (Task 4.4): invoices and pay.

Included under /api/v1/finance/ from config.urls.
"""

from billing.views import InvoiceListCreateView, PayView, RazorpayOrderView
from django.urls import path

urlpatterns = [
    path("invoices", InvoiceListCreateView.as_view(), name="invoice-list-create"),
    path(
        "invoices/<uuid:invoice_id>/razorpay-order",
        RazorpayOrderView.as_view(),
        name="razorpay-order",
    ),
    path("pay", PayView.as_view(), name="pay"),
]
