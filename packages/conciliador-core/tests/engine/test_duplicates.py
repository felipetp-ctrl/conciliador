from datetime import date

from conciliador_core.engine.duplicates import find_probable_duplicates
from conciliador_core.models import Direction, ExpectedItem, ItemStatus, Source

DOC = "52998224725"


def mk(
    id: str,
    source: Source = Source.NFE,
    day: int = 10,
    doc: str | None = DOC,
    number: str | None = None,
    cents: int = 100_00,
    direction: Direction = Direction.INFLOW,
    status: ItemStatus = ItemStatus.OPEN,
) -> ExpectedItem:
    return ExpectedItem(
        id=id,
        source=source,
        direction=direction,
        amount_cents=cents,
        due_on=date(2026, 10, day),
        issued_on=None,
        counterpart_doc=doc,
        counterpart_name=None,
        document_number=number,
        status=status,
    )


def test_three_days_apart_pairs() -> None:
    a = mk("b", Source.NFE, 10)
    b = mk("a", Source.CSV, 13)
    assert find_probable_duplicates([a, b]) == [("a", "b")]


def test_six_days_different_numbers_no_pair() -> None:
    a = mk("a", Source.NFE, 10, number="1")
    b = mk("b", Source.CSV, 16, number="2")
    assert find_probable_duplicates([a, b]) == []


def test_six_days_same_number_ignoring_zeros_pairs() -> None:
    a = mk("a", Source.NFE, 10, number="00123")
    b = mk("b", Source.CSV, 20, number="123")
    assert find_probable_duplicates([a, b]) == [("a", "b")]


def test_zero_numbers_never_match() -> None:
    a = mk("a", Source.NFE, 10, number="000")
    b = mk("b", Source.CSV, 20, number="0")
    c = mk("c", Source.CSV, 20, number="")
    assert find_probable_duplicates([a, b, c]) == []


def test_same_source_never_pairs() -> None:
    assert find_probable_duplicates([mk("a"), mk("b")]) == []


def test_different_direction_or_amount_no_pair() -> None:
    a = mk("a", Source.NFE)
    assert find_probable_duplicates([a, mk("b", Source.CSV, direction=Direction.OUTFLOW)]) == []
    assert find_probable_duplicates([a, mk("c", Source.CSV, cents=1)]) == []


def test_doc_must_match_when_both_have_it() -> None:
    a = mk("a", Source.NFE)
    assert find_probable_duplicates([a, mk("b", Source.CSV, doc="11222333000181")]) == []


def test_missing_doc_on_either_side_is_ignored() -> None:
    a = mk("a", Source.NFE, doc=None)
    b = mk("b", Source.CSV)
    c = mk("c", Source.CSV, doc="11222333000181")
    assert find_probable_duplicates([a, b, c]) == [("a", "b"), ("a", "c")]


def test_cancelled_ignored() -> None:
    a = mk("a", Source.NFE, status=ItemStatus.CANCELLED)
    assert find_probable_duplicates([a, mk("b", Source.CSV)]) == []


def test_sorted_and_deduplicated() -> None:
    items = [mk("z", Source.NFE), mk("y", Source.CSV), mk("x", Source.MANUAL), mk("y", Source.CSV)]
    assert find_probable_duplicates(items) == [("x", "y"), ("x", "z"), ("y", "z")]
