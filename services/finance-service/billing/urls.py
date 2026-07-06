"""Billing endpoints (Task 4.4): invoices and pay.

Included under /api/v1/finance/ from config.urls.
"""

from billing.views import (
    FeeStructureListCreateView,
    InvoiceListCreateView,
    PayView,
    RazorpayOrderView,
    ReceiptPdfByInvoiceView,
    ReceiptPdfView,
    VerifyReceiptView,
)
from django.urls import path

urlpatterns = [
    path("invoices", InvoiceListCreateView.as_view(), name="invoice-list-create"),
    path(
        "invoices/<uuid:invoice_id>/razorpay-order",
        RazorpayOrderView.as_view(),
        name="razorpay-order",
    ),
    path("pay", PayView.as_view(), name="pay"),
    path("fee-structures", FeeStructureListCreateView.as_view(), name="fee-structure-list-create"),
    path("receipts/verify", VerifyReceiptView.as_view(), name="receipt-verify"),
    path(
        "receipts/by-invoice/<uuid:invoice_id>/pdf",
        ReceiptPdfByInvoiceView.as_view(),
        name="receipt-pdf-by-invoice",
    ),
    path("receipts/<uuid:receipt_id>/pdf", ReceiptPdfView.as_view(), name="receipt-pdf"),
]
