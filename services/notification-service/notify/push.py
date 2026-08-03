"""Push delivery, behind an interface.

Expo today; FCM later without touching the consumer. Expo is the choice
because it removes the entire APNs-certificate and google-services.json
burden, which is real setup cost for a capability the platform needs to
demonstrate, not to operate at scale.

Delivery is best-effort by design: the in-app inbox row is the source of
truth and is written first. A push outage must never fail an event consumer,
because that would make a notification failure look like a payment failure.
"""

import logging
from typing import Protocol

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
PUSH_TIMEOUT_SECONDS = 5


class PushChannel(Protocol):
    def send(self, tokens: list[str], title: str, body: str, data: dict) -> list[str]:
        """Deliver to each token. Returns tokens the provider says are dead."""
        ...


class ExpoPushChannel:
    def send(self, tokens: list[str], title: str, body: str, data: dict) -> list[str]:
        if not tokens:
            return []

        messages = [{"to": token, "title": title, "body": body, "data": data} for token in tokens]

        try:
            response = requests.post(EXPO_PUSH_URL, json=messages, timeout=PUSH_TIMEOUT_SECONDS)
            response.raise_for_status()
            receipts = response.json().get("data", [])
        except Exception:
            logger.exception("Push delivery failed; inbox rows are unaffected.")
            return []

        stale = []
        for token, receipt in zip(tokens, receipts, strict=False):
            details = receipt.get("details") or {}
            if receipt.get("status") == "error" and details.get("error") == "DeviceNotRegistered":
                stale.append(token)
        return stale


class NullPushChannel:
    """Used in tests and local runs — accepts everything, sends nothing."""

    def send(self, tokens: list[str], title: str, body: str, data: dict) -> list[str]:
        return []


def get_channel() -> PushChannel:
    """Opt-in: a developer running the stack locally must not be able to
    accidentally fire real notifications at students' phones."""
    if getattr(settings, "PUSH_ENABLED", False):
        return ExpoPushChannel()
    return NullPushChannel()
