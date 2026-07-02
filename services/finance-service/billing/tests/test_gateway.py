"""Tests for the simulated payment gateway (Task 4.3).

No real Razorpay/Stripe call is made anywhere here — ``SimulatedGateway`` is
an in-process, deterministic stand-in behind the ``PaymentGateway`` Protocol,
so these are pure-Python tests with no DB access required.
"""

from decimal import Decimal

from billing.gateway import SimulatedGateway


def test_whole_rupee_amount_succeeds():
    result = SimulatedGateway().charge(Decimal("100.00"), "key-1")
    assert result.success is True
    assert result.gateway_ref != ""


def test_dot_99_amount_fails():
    result = SimulatedGateway().charge(Decimal("9.99"), "key-2")
    assert result.success is False


def test_same_idempotency_key_returns_same_result():
    gateway = SimulatedGateway()
    first = gateway.charge(Decimal("100.00"), "key-3")
    second = gateway.charge(Decimal("100.00"), "key-3")
    assert first == second
    assert first.gateway_ref == second.gateway_ref


def test_normal_fee_amount_succeeds():
    result = SimulatedGateway().charge(Decimal("4500.00"), "key-4")
    assert result.success is True
