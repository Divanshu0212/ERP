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
from billing.models import Invoice, Payment
from billing.serializers import InvoiceCreateSerializer, InvoiceSerializer, PaySerializer
from django.db import transaction
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

        order = razorpay_gateway.create_order(invoice.amount, receipt=f"invoice-{invoice.id}")
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
