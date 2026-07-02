"""Payment gateway abstraction: a swappable interface plus an in-process
deterministic simulator.

``PaymentGateway`` is a ``typing.Protocol`` — any object with a matching
``charge(amount, idempotency_key) -> ChargeResult`` method satisfies it.
``SimulatedGateway`` is the only implementation for now; a real adapter
(Razorpay, Stripe, ...) can be dropped in later behind the same signature
without touching call sites.

Determinism convention (test hook)
-----------------------------------
``SimulatedGateway`` never calls out over the network. Its outcome is a pure
function of the ``amount``'s cents:

* cents == ``.99`` (e.g. 9.99, 99.99)  -> failure. This lets tests exercise
  the failure path on demand by picking an amount ending in .99.
* anything else, including the common ``.00`` case (e.g. 100.00, 4500.00)
  -> success. Ordinary fees (tuition, hostel, ...) are whole-rupee amounts
  and always succeed under this rule.

This is intentionally documented and stable: it is the "simulated in-process
gateway" test mode called for by the design spec, not an attempt to model a
real gateway's behavior.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class ChargeResult:
    success: bool
    gateway_ref: str
    message: str


class PaymentGateway(Protocol):
    """Interface a real gateway adapter must implement to be swapped in."""

    def charge(self, amount: Decimal, idempotency_key: str) -> ChargeResult: ...


class SimulatedGateway:
    """Deterministic, in-process stand-in for a real payment gateway.

    No network calls and no secrets are involved. See module docstring for
    the determinism convention (``.99`` cents = failure, everything else =
    success).

    Idempotency: results are cached in-memory keyed by ``idempotency_key``,
    so repeated calls with the same key return the identical ``ChargeResult``
    (same ``success`` and ``gateway_ref``) regardless of the amount passed on
    the repeat call. This mirrors how a real gateway's idempotency-key
    support behaves, and proves idempotency at the gateway layer itself.
    """

    def __init__(self) -> None:
        self._results: dict[str, ChargeResult] = {}

    def charge(self, amount: Decimal, idempotency_key: str) -> ChargeResult:
        if idempotency_key in self._results:
            return self._results[idempotency_key]

        is_failure = (amount * 100).to_integral_value() % 100 == 99

        if is_failure:
            result = ChargeResult(
                success=False,
                gateway_ref=f"SIM-FAIL-{idempotency_key[:12]}",
                message="Simulated decline: amount ends in .99 (test hook)",
            )
        else:
            result = ChargeResult(
                success=True,
                gateway_ref=f"SIM-{idempotency_key[:12]}",
                message="Simulated charge succeeded",
            )

        self._results[idempotency_key] = result
        return result
