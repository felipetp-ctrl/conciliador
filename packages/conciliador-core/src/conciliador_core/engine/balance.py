"""Checagem de saldo final e de lacunas entre extratos."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from conciliador_core.models import BankTransaction


@dataclass(frozen=True)
class BalanceCheck:
    expected_closing_cents: int
    reported_closing_cents: int | None
    difference_cents: int | None
    ok: bool


def check_balance(
    opening_cents: int,
    transactions: Sequence[BankTransaction],
    reported_closing_cents: int | None,
) -> BalanceCheck:
    expected = opening_cents + sum(t.amount_cents for t in transactions)
    if reported_closing_cents is None:
        return BalanceCheck(expected, None, None, True)
    difference = reported_closing_cents - expected
    return BalanceCheck(expected, reported_closing_cents, difference, difference == 0)


def has_gap(previous_end: date | None, start: date | None) -> bool:
    """True quando há dias sem cobertura entre o fim de um extrato e o início do próximo."""
    if previous_end is None or start is None:
        return False
    return start > previous_end + timedelta(days=1)
