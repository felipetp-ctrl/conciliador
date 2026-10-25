from datetime import date

import pytest
from conciliador_core.engine.status import ItemSituation, ItemState, classify_item
from conciliador_core.models import Direction, ExpectedItem, ItemStatus, Source

DUE = date(2026, 10, 10)


def mk(status: ItemStatus = ItemStatus.OPEN) -> ExpectedItem:
    return ExpectedItem(
        id="i",
        source=Source.NFE,
        direction=Direction.INFLOW,
        amount_cents=1000,
        due_on=DUE,
        issued_on=None,
        counterpart_doc=None,
        counterpart_name=None,
        document_number=None,
        status=status,
    )


def test_partial_before_due_is_pending() -> None:
    assert classify_item(mk(), 400, False, date(2026, 10, 1)) == ItemSituation(
        ItemState.PENDING, 600
    )


def test_due_day_is_still_pending() -> None:
    assert classify_item(mk(), 0, False, DUE).state is ItemState.PENDING


def test_after_due_is_overdue() -> None:
    assert classify_item(mk(), 400, False, date(2026, 10, 11)) == ItemSituation(
        ItemState.OVERDUE, 600
    )


def test_closed_with_difference_is_settled() -> None:
    assert classify_item(mk(), 400, True, date(2026, 12, 1)) == ItemSituation(ItemState.SETTLED, 0)


def test_full_and_over_payment_settled() -> None:
    assert classify_item(mk(), 1000, False, DUE) == ItemSituation(ItemState.SETTLED, 0)
    assert classify_item(mk(), 1500, False, DUE) == ItemSituation(ItemState.SETTLED, 0)


def test_cancelled() -> None:
    sit = classify_item(mk(ItemStatus.CANCELLED), 0, False, DUE)
    assert sit.state is ItemState.CANCELLED


def test_negative_linked_raises() -> None:
    with pytest.raises(ValueError):
        classify_item(mk(), -1, False, DUE)
