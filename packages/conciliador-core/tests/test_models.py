from datetime import date

import pytest
from conciliador_core.models import (
    BankAccountRef,
    BankTransaction,
    Direction,
    ExpectedItem,
    ItemStatus,
    Source,
    Statement,
)


def _item(amount: int) -> ExpectedItem:
    return ExpectedItem(
        id="x",
        source=Source.NFE,
        direction=Direction.INFLOW,
        amount_cents=amount,
        due_on=date(2026, 1, 10),
        issued_on=None,
        counterpart_doc=None,
        counterpart_name=None,
        document_number=None,
    )


def _tx(amount: int) -> BankTransaction:
    return BankTransaction(
        fitid="1",
        posted_on=date(2026, 1, 10),
        amount_cents=amount,
        memo="m",
        documents=(),
        dedup_key="k",
    )


def test_expected_item_rejects_non_positive() -> None:
    for bad in (0, -1):
        with pytest.raises(ValueError, match="amount_cents"):
            _item(bad)


def test_expected_item_defaults() -> None:
    item = _item(100)
    assert item.status is ItemStatus.OPEN
    assert item.withholdings == ()
    assert item.gross_cents is None
    assert item.branch_cnpj is None


def test_direction() -> None:
    assert _tx(-100).direction is Direction.OUTFLOW
    assert _tx(100).direction is Direction.INFLOW


def test_enums_and_statement() -> None:
    assert Direction.INFLOW == "inflow"
    assert {s.name for s in Source} == {"NFE", "NFSE", "CSV", "MANUAL"}
    acct = BankAccountRef(bank_id="001", branch=None, account_number="1")
    st = Statement(account=acct, start=None, end=None, ledger_balance_cents=None, transactions=())
    assert st.transactions == ()
