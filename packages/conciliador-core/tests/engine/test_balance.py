from datetime import date

from conciliador_core.engine.balance import BalanceCheck, check_balance, has_gap
from conciliador_core.models import BankTransaction


def tx(cents: int) -> BankTransaction:
    return BankTransaction(
        fitid=None,
        posted_on=date(2026, 10, 1),
        amount_cents=cents,
        memo="",
        documents=(),
        dedup_key=f"k{cents}",
    )


def test_balance_ok() -> None:
    assert check_balance(10000, [tx(5000), tx(-2000)], 13000) == BalanceCheck(13000, 13000, 0, True)


def test_balance_off_by_one() -> None:
    res = check_balance(10000, [tx(5000), tx(-2000)], 12999)
    assert res.difference_cents == -1
    assert res.ok is False


def test_balance_not_reported_is_ok() -> None:
    res = check_balance(0, [tx(1)], None)
    assert (res.expected_closing_cents, res.difference_cents, res.ok) == (1, None, True)


def test_has_gap() -> None:
    assert has_gap(date(2026, 9, 30), date(2026, 10, 1)) is False
    assert has_gap(date(2026, 9, 30), date(2026, 10, 3)) is True
    assert has_gap(None, date(2026, 10, 3)) is False
    assert has_gap(date(2026, 9, 30), None) is False
