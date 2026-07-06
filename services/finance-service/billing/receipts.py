"""Payment receipt generation: PDF (reportlab) + embedded QR (qrcode) linking
to a verify page, plus an HMAC-signed verification_token.

Called synchronously from billing.views.PayView inside its existing
transaction.atomic() block on payment success — see that module's docstring
for why this stays synchronous rather than becoming a new event-consumer
path (no request context available there to resolve a URL correctly, and no
precedent in this codebase for a service consuming its own published event).

HMAC choice: RECEIPT_HMAC_SECRET (config.settings) is a signing secret
distinct from JWT_SIGNING_KEY (shared inter-service auth secret) so that
rotating one never invalidates the other. The token itself carries no
embedded data (unlike a JWT) — it's HMAC-SHA256(receipt_id_bytes, secret)
hex-encoded, opaque, and verify_token() below re-derives the same digest for
a receipt_id looked up from the DB and compares with hmac.compare_digest
(constant-time, avoiding timing side-channels on the comparison itself).
"""

import hashlib
import hmac
import io
import uuid
from typing import TYPE_CHECKING

import qrcode
from django.conf import settings
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

if TYPE_CHECKING:
    from billing.models import Receipt


def _sign(receipt_id: uuid.UUID) -> str:
    return hmac.new(
        settings.RECEIPT_HMAC_SECRET.encode(), str(receipt_id).encode(), hashlib.sha256
    ).hexdigest()


def verify_token(token: str) -> uuid.UUID | None:
    """Return the receipt_id this token was issued for, or None if the token
    doesn't match any receipt. The token doesn't embed the id, so we look up
    the Receipt by its stored verification_token, then re-derive the expected
    HMAC for that receipt's id and constant-time compare — a stored token can
    only survive if it genuinely equals HMAC(receipt_id, secret). Kept here as
    the single source of truth for "does this token match this receipt" so PDF
    generation and verification never drift.
    """
    from billing.models import Receipt

    receipt = Receipt.all_objects.filter(verification_token=token).first()
    if receipt is None:
        return None
    expected = _sign(receipt.id)
    if not hmac.compare_digest(expected, token):
        return None
    return receipt.id


def _render_pdf(payment, receipt_id: uuid.UUID, receipt_no: str, verify_url: str) -> bytes:
    invoice = payment.invoice
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    pdf.setFont("Helvetica-Bold", 16)
    university_name = invoice.university_name or "SU-ERP"
    pdf.drawCentredString(width / 2, height - 30 * mm, university_name)

    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawCentredString(width / 2, height - 40 * mm, "Payment Receipt")

    pdf.setFont("Helvetica", 11)
    lines = [
        f"Receipt No: {receipt_no}",
        f"Purpose: {invoice.purpose}",
        f"Amount: {invoice.amount}",
        f"Status: {payment.status}",
        f"Gateway Reference: {payment.gateway_ref}",
        f"Paid On: {payment.created_at.strftime('%Y-%m-%d %H:%M UTC')}",
    ]
    y = height - 55 * mm
    for line in lines:
        pdf.drawString(25 * mm, y, line)
        y -= 8 * mm

    qr_image = qrcode.make(verify_url)
    qr_buffer = io.BytesIO()
    qr_image.save(qr_buffer, format="PNG")
    qr_buffer.seek(0)
    from reportlab.lib.utils import ImageReader

    pdf.drawImage(ImageReader(qr_buffer), 25 * mm, y - 45 * mm, width=35 * mm, height=35 * mm)

    pdf.setFont("Helvetica", 8)
    pdf.drawString(25 * mm, y - 50 * mm, f"Verify: {verify_url}")

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def generate_receipt(payment) -> "Receipt":
    """Create and return a Receipt for a successful Payment, rendering the
    PDF (with embedded QR + HMAC token) once and storing the bytes. Caller
    (billing.views.PayView) must already hold a transaction.atomic() block —
    this performs a single Receipt.objects.create() and no I/O beyond
    in-memory PDF/QR rendering, so it's safe to call inline.
    """
    from billing.models import Receipt

    receipt_id = uuid.uuid4()
    receipt_no = f"RCPT-{receipt_id.hex[:12].upper()}"
    token = _sign(receipt_id)
    verify_url = f"{settings.FRONTEND_URL}/verify-receipt?token={token}"

    pdf_bytes = _render_pdf(payment, receipt_id, receipt_no, verify_url)

    return Receipt.objects.create(
        id=receipt_id,
        tenant_id=payment.tenant_id,
        payment=payment,
        receipt_no=receipt_no,
        pdf_data=pdf_bytes,
        verification_token=token,
        verify_url=verify_url,
    )
