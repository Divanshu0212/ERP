"""Razorpay gateway helper: real (test-mode) payment adapter, additive to the
in-process ``SimulatedGateway`` (see finance-service's ``billing/gateway.py``).

This module is the *real* payment path. Credentials are read from Django
settings (``RAZORPAY_KEY_ID``/``RAZORPAY_KEY_SECRET``), which each service
loads from the environment via ``django-environ`` with empty-string defaults.
When neither is set, ``is_configured()`` returns ``False`` and call sites fall
back to their simulated/dev behavior — no network calls, no secrets required.

The ``razorpay`` SDK is imported lazily inside each function so that importing
this module (and running the simulated-mode path) never requires the package
to be installed.
"""

from decimal import Decimal

from django.conf import settings


def is_configured() -> bool:
    """True when both Razorpay credentials are present in settings.

    Call sites use this to decide between the real Razorpay path and the
    simulated-mode fallback — a service boots and serves fine with the keys
    unset.
    """
    return bool(
        getattr(settings, "RAZORPAY_KEY_ID", "") and getattr(settings, "RAZORPAY_KEY_SECRET", "")
    )


def create_order(amount: Decimal, receipt: str) -> dict:
    """Create a Razorpay order for ``amount`` (in rupees).

    Returns ``{order_id, amount, currency, key_id}`` — the shape a frontend
    checkout needs to open the Razorpay widget. ``amount`` is converted to
    integer paise for the API. Raises if ``is_configured()`` is False (callers
    must guard with it first).
    """
    import razorpay

    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    amount_paise = int((amount * 100).to_integral_value())
    order = client.order.create(
        {
            "amount": amount_paise,
            "currency": "INR",
            "receipt": receipt,
            "payment_capture": 1,
        }
    )
    return {
        "order_id": order["id"],
        "amount": str(amount),
        "currency": "INR",
        "key_id": settings.RAZORPAY_KEY_ID,
    }


def verify_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """Verify a Razorpay payment signature (proof the client actually paid).

    Returns True if the HMAC signature is valid for ``(order_id, payment_id)``,
    False on a ``SignatureVerificationError``. Never makes a network call —
    verification is a local HMAC check against the key secret.
    """
    import razorpay

    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    try:
        client.utility.verify_payment_signature(
            {
                "razorpay_order_id": order_id,
                "razorpay_payment_id": payment_id,
                "razorpay_signature": signature,
            }
        )
        return True
    except razorpay.errors.SignatureVerificationError:
        return False
