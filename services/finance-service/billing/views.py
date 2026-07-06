"""Invoice and pay endpoints (Task 4.4).

``PayView`` is the finance half of the hostel-allocation saga: it charges a
simulated gateway and, on both success and failure, commits the resulting
``Payment`` row, the ``Invoice`` status transition, and the
``finance.payment.success``/``finance.payment.failed`` outbox event in a
single ``transaction.atomic()`` block — the transactional-outbox guarantee
(state and event commit or roll back together; nothing here talks to
RabbitMQ directly, ``drain_outbox_task`` relays it later).

Idempotency: replaying the same ``idempotency_key`` for the same invoice
(e.g. a retried request under load, or a duplicate client submit) must not
double-charge or double-emit. This is enforced by storing the
``idempotency_key`` on ``Payment`` and, before ever calling the gateway,
checking for a prior ``Payment`` row with the same ``(invoice, idempotency_
key)`` — if found, its outcome is returned as-is. An already-``paid``
invoice is also treated idempotently (repeat pay on a paid invoice returns
success without touching the gateway or emitting a new event).
"""

from billing.gateway import ChargeResult, SimulatedGateway
from billing.models import FeeStructure, Invoice, Payment, Receipt
from billing.receipts import generate_receipt, verify_token
from billing.serializers import (
    FeeStructureCreateSerializer,
    FeeStructureSerializer,
    InvoiceCreateSerializer,
    InvoiceSerializer,
    PaySerializer,
)
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from suerp_common import razorpay_gateway
from suerp_common.envelope import fail, ok
from suerp_common.outbox import publish_event
from suerp_common.permissions import role_required


class InvoiceListCreateView(ListAPIView):
    """GET lists invoices (tenant-scoped, paginated); POST creates one.

    POST exists for test/manual convenience — in normal operation invoices
    are created from upstream events (e.g. hostel allocation), not by direct
    API call.
    """

    serializer_class = InvoiceSerializer

    def get_permissions(self):
        # GET: any authenticated user may list (tenant-scoped). POST: admin only
        # — invoices are normally created from upstream events, direct creation
        # is an admin/operator action.
        if self.request.method == "POST":
            return [role_required("admin")()]
        return [IsAuthenticated()]

    def get_queryset(self):
        return Invoice.objects.all().order_by("-created_at")

    def post(self, request):
        serializer = InvoiceCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid invoice payload.", errors=serializer.errors, status=400)

        invoice = serializer.save(tenant_id=request.tenant_id)
        return ok(InvoiceSerializer(invoice).data, message="Invoice created.", status=201)


class FeeStructureListCreateView(ListAPIView):
    """GET lists fee structures (tenant-scoped, paginated), any authenticated
    role — a warden approving a room request needs to read these to build a
    fee picker. POST creates one, admin-only.
    """

    serializer_class = FeeStructureSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [role_required("admin")()]
        return [IsAuthenticated()]

    def get_queryset(self):
        return FeeStructure.objects.all().order_by("purpose")

    def post(self, request):
        serializer = FeeStructureCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid fee structure payload.", errors=serializer.errors, status=400)

        try:
            fee_structure = serializer.save(tenant_id=request.tenant_id)
        except IntegrityError:
            return fail(
                "A fee structure with this purpose already exists for this tenant.",
                status=400,
            )

        return ok(
            FeeStructureSerializer(fee_structure).data,
            message="Fee structure created.",
            status=201,
        )


def _deny_if_not_owner(request, receipt: Receipt):
    """Ownership gate for receipt-PDF downloads.

    A student may download ONLY their own receipt (the one whose invoice's
    ``student_id`` is their own user id). Warden/admin may download ANY receipt
    in their tenant — they need this for verification/audit. Returns a 403
    ``fail`` response when a student requests someone else's receipt, else None.
    """
    if getattr(request.user, "role", None) == "student":
        if str(receipt.payment.invoice.student_id) != str(request.user.id):
            return fail("You may only download your own receipt.", status=403)
    return None


def _payment_outcome(payment: Payment) -> dict:
    return {
        "invoice_id": str(payment.invoice_id),
        "payment_id": str(payment.id),
        "status": payment.status,
        "gateway_ref": payment.gateway_ref,
    }


class RazorpayOrderView(APIView):
    """POST /api/v1/finance/invoices/<uuid:invoice_id>/razorpay-order.

    Creates a Razorpay order for the invoice's amount so a frontend can open
    the checkout widget. Tenant-scoped (cross-tenant/unknown invoice -> 404).
    Returns 400 if Razorpay isn't configured on this server (the pay flow can
    still be exercised via the simulated path in that case).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, invoice_id):
        invoice = get_object_or_404(Invoice.objects, id=invoice_id)

        if not razorpay_gateway.is_configured():
            return fail("Razorpay is not configured on this server.", status=400)

        order = razorpay_gateway.create_order(invoice.amount, receipt=f"inv-{invoice.id}")
        return ok(order, message="Razorpay order created.")


class PayView(APIView):
    def post(self, request):
        serializer = PaySerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid pay request.", errors=serializer.errors, status=400)

        invoice_id = serializer.validated_data["invoice_id"]
        idempotency_key = serializer.validated_data["idempotency_key"]
        razorpay_order_id = serializer.validated_data.get("razorpay_order_id")
        razorpay_payment_id = serializer.validated_data.get("razorpay_payment_id")
        razorpay_signature = serializer.validated_data.get("razorpay_signature")
        has_razorpay_proof = all((razorpay_order_id, razorpay_payment_id, razorpay_signature))

        with transaction.atomic():
            invoice = get_object_or_404(Invoice.objects.select_for_update(), id=invoice_id)

            existing_payment = Payment.objects.filter(
                invoice=invoice, idempotency_key=idempotency_key
            ).first()
            if existing_payment is not None:
                return ok(_payment_outcome(existing_payment), message="Payment already processed.")

            if invoice.status == Invoice.Status.PAID:
                # Paid via a different idempotency key already — replaying a
                # pay call must not double-charge. Return the existing
                # successful payment without touching the gateway again.
                prior = (
                    invoice.payments.filter(status=Payment.Status.SUCCESS)
                    .order_by("-created_at")
                    .first()
                )
                if prior is not None:
                    return ok(_payment_outcome(prior), message="Invoice already paid.")

            if has_razorpay_proof:
                # Real Razorpay path: verify the client's proof-of-payment
                # signature. Success/failure map onto exactly the same commit
                # branches as the simulated gateway below.
                verified = razorpay_gateway.verify_signature(
                    razorpay_order_id, razorpay_payment_id, razorpay_signature
                )
                if verified:
                    result = ChargeResult(
                        success=True,
                        gateway_ref=razorpay_payment_id,
                        message="Razorpay payment verified.",
                    )
                else:
                    result = ChargeResult(
                        success=False,
                        gateway_ref=razorpay_payment_id,
                        message="Razorpay signature verification failed.",
                    )
            else:
                result = SimulatedGateway().charge(invoice.amount, idempotency_key)

            if result.success:
                payment = Payment.objects.create(
                    tenant_id=invoice.tenant_id,
                    invoice=invoice,
                    amount=invoice.amount,
                    status=Payment.Status.SUCCESS,
                    gateway_ref=result.gateway_ref,
                    idempotency_key=idempotency_key,
                )
                invoice.status = Invoice.Status.PAID
                invoice.idempotency_key = idempotency_key
                invoice.save(update_fields=["status", "idempotency_key"])
                generate_receipt(payment)

                publish_event(
                    "finance.payment.success",
                    tenant_id=str(invoice.tenant_id),
                    payload={
                        "invoice_id": str(invoice.id),
                        "student_id": str(invoice.student_id),
                        "purpose": invoice.purpose,
                        "amount": str(invoice.amount),
                    },
                )
            else:
                payment = Payment.objects.create(
                    tenant_id=invoice.tenant_id,
                    invoice=invoice,
                    amount=invoice.amount,
                    status=Payment.Status.FAILED,
                    gateway_ref=result.gateway_ref,
                    idempotency_key=idempotency_key,
                )
                invoice.status = Invoice.Status.FAILED
                invoice.idempotency_key = idempotency_key
                invoice.save(update_fields=["status", "idempotency_key"])

                publish_event(
                    "finance.payment.failed",
                    tenant_id=str(invoice.tenant_id),
                    payload={
                        "invoice_id": str(invoice.id),
                        "student_id": str(invoice.student_id),
                        "purpose": invoice.purpose,
                    },
                )

            return ok(_payment_outcome(payment), message=result.message)


class ReceiptPdfView(APIView):
    """GET /api/v1/finance/receipts/<uuid:receipt_id>/pdf — download the
    stored PDF bytes as-is (rendered once at payment-success time, see
    billing.receipts.generate_receipt). Tenant-scoped: cross-tenant/unknown
    receipt_id -> 404, same pattern as RazorpayOrderView.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, receipt_id):
        from django.http import HttpResponse

        receipt = get_object_or_404(Receipt.objects, id=receipt_id)
        denied = _deny_if_not_owner(request, receipt)
        if denied is not None:
            return denied
        response = HttpResponse(bytes(receipt.pdf_data), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{receipt.receipt_no}.pdf"'
        return response


class VerifyReceiptView(APIView):
    """POST /api/v1/finance/receipts/verify — warden/admin checks a
    verification_token (scanned from the QR or typed from the plain-text
    code beneath it). Returns {valid, receipt_no, amount, purpose,
    university_name, paid_on} on a match, {valid: false} otherwise — never
    404s on a bad token, since "this token is invalid" is itself a normal,
    expected verification outcome, not an error.
    """

    permission_classes = [role_required("warden", "admin")]

    def post(self, request):
        token = request.data.get("token", "")
        receipt_id = verify_token(token)
        if receipt_id is None:
            return ok({"valid": False})

        # verify_token() resolves against Receipt.all_objects (tenant-bypassing
        # by design — the token itself is the authority). A token that's
        # cryptographically valid but belongs to another tenant must still
        # read as "not valid for you" here, not 500 — filter().first() instead
        # of a tenant-scoped get() so a cross-tenant hit degrades to
        # {"valid": False} instead of an uncaught DoesNotExist.
        receipt = Receipt.objects.filter(id=receipt_id).first()
        if receipt is None:
            return ok({"valid": False})

        invoice = receipt.payment.invoice
        return ok(
            {
                "valid": True,
                "receipt_no": receipt.receipt_no,
                "amount": str(invoice.amount),
                "purpose": invoice.purpose,
                "university_name": invoice.university_name,
                "paid_on": receipt.created_at.isoformat(),
            }
        )


class ReceiptPdfByInvoiceView(APIView):
    """GET /api/v1/finance/receipts/by-invoice/<uuid:invoice_id>/pdf —
    convenience lookup for the student invoice table, which only has an
    invoice_id on hand (Invoice and Receipt aren't joined in any response
    the student page already fetches). 404s if the invoice has no receipt
    yet (unpaid, or paid before this feature existed).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, invoice_id):
        from django.http import HttpResponse

        receipt = get_object_or_404(Receipt.objects, payment__invoice_id=invoice_id)
        denied = _deny_if_not_owner(request, receipt)
        if denied is not None:
            return denied
        response = HttpResponse(bytes(receipt.pdf_data), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{receipt.receipt_no}.pdf"'
        return response
