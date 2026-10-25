from datetime import date

import pytest
from conciliador_core.engine.config import MatchConfig
from conciliador_core.engine.matcher import Rule, RuleBasedProvider, Suggestion
from conciliador_core.models import BankTransaction, Direction, ExpectedItem, ItemStatus, Source

DOC = "52998224725"


def tx(
    day: int,
    cents: int,
    memo: str = "",
    docs: tuple[str, ...] = (),
    key: str | None = None,
    month: int = 10,
) -> BankTransaction:
    return BankTransaction(
        fitid=None,
        posted_on=date(2026, month, day),
        amount_cents=cents,
        memo=memo,
        documents=docs,
        dedup_key=key or f"k{day}-{cents}-{memo}",
    )


def item(
    id: str,
    day_due: int,
    cents: int,
    doc: str | None = None,
    number: str | None = None,
    direction: Direction = Direction.INFLOW,
    status: ItemStatus = ItemStatus.OPEN,
) -> ExpectedItem:
    return ExpectedItem(
        id=id,
        source=Source.MANUAL,
        direction=direction,
        amount_cents=cents,
        due_on=date(2026, 10, day_due),
        issued_on=None,
        counterpart_doc=doc,
        counterpart_name=None,
        document_number=number,
        status=status,
    )


def suggest(
    txs: list[BankTransaction],
    items: list[ExpectedItem],
    config: MatchConfig | None = None,
    **kw: frozenset[tuple[str, str]] | frozenset[str],
) -> list[Suggestion]:
    return RuleBasedProvider().suggest(txs, items, config or MatchConfig(), **kw)  # type: ignore[arg-type]


def primaries(s: list[Suggestion]) -> list[Suggestion]:
    return [x for x in s if x.is_primary]


def test_document_rule_wins():
    s = suggest([tx(16, 1000, docs=(DOC,))], [item("a", 15, 1000, doc=DOC), item("b", 15, 1000)])
    assert [(x.item_id, x.rule, x.score) for x in s] == [("a", Rule.DOCUMENT, 299)]
    assert s[0].is_primary
    assert s[0].reason == "Mesmo valor; CPF/CNPJ no histórico; 1 dia após o vencimento"


def test_number_rule():
    s = suggest(
        [tx(15, 1000, memo="PAG NF 000123")],
        [item("a", 15, 1000, number="123"), item("b", 15, 1000, number="9")],
    )
    assert [(x.item_id, x.rule, x.score, x.is_primary) for x in s] == [
        ("a", Rule.NUMBER, 200, True)
    ]
    assert s[0].reason == "Mesmo valor; Nº do documento no histórico; no dia do vencimento"


def test_number_requires_isolated_token():
    assert (
        suggest([tx(15, 1000, memo="NF 1234")], [item("a", 15, 1000, number="123")])[0].rule
        == Rule.UNIQUE
    )
    assert (
        suggest([tx(15, 1000, memo="NF123")], [item("a", 15, 1000, number="123")])[0].rule
        == Rule.NUMBER
    )
    assert (
        suggest([tx(15, 1000, memo="NF 123")], [item("a", 15, 1000, number="0123")])[0].rule
        == Rule.NUMBER
    )


@pytest.mark.parametrize("number", ["0", "000", ""])
def test_zero_or_empty_number_never_matches(number):
    s = suggest([tx(15, 1000, memo="PAG 0 000")], [item("a", 15, 1000, number=number)])
    assert s[0].rule == Rule.UNIQUE


def test_unique_rule():
    s = suggest([tx(13, 1000)], [item("a", 15, 1000)])
    assert [(x.item_id, x.rule, x.score, x.is_primary) for x in s] == [("a", Rule.UNIQUE, 98, True)]
    assert s[0].reason == "Mesmo valor; 2 dias antes do vencimento"


def test_unique_with_several_candidates_is_ambiguous():
    s = suggest([tx(15, 1000)], [item("a", 14, 1000), item("b", 17, 1000)])
    assert [(x.item_id, x.rule, x.score, x.is_primary) for x in s] == [
        ("a", Rule.AMBIGUOUS, 99, False),
        ("b", Rule.AMBIGUOUS, 98, False),
    ]


def test_two_equal_invoices_same_client_are_ambiguous():
    s = suggest(
        [tx(15, 1000, docs=(DOC,))],
        [item("a", 12, 1000, doc=DOC), item("b", 18, 1000, doc=DOC)],
    )
    assert {(x.item_id, x.rule, x.is_primary) for x in s} == {
        ("a", Rule.AMBIGUOUS, False),
        ("b", Rule.AMBIGUOUS, False),
    }


def test_stronger_rule_with_single_candidate_returns_only_primary():
    s = suggest(
        [tx(15, 1000, docs=(DOC,))],
        [item("a", 15, 1000, doc=DOC), item("b", 15, 1000), item("c", 14, 1000)],
    )
    assert [(x.item_id, x.is_primary) for x in s] == [("a", True)]


@pytest.mark.parametrize("day,match", [(10, True), (9, False), (25, True), (26, False)])
def test_window_bounds_inclusive(day, match):
    assert bool(suggest([tx(day, 1000)], [item("a", 15, 1000)])) is match


def test_direction_must_match():
    assert suggest([tx(15, -1000)], [item("a", 15, 1000)]) == []
    assert suggest([tx(15, -1000)], [item("a", 15, 1000, direction=Direction.OUTFLOW)])


def test_zero_amount_never_matches():
    assert suggest([tx(15, 0)], [item("a", 15, 1000)]) == []


def test_tolerance():
    cfg = MatchConfig(tolerance_cents=5)
    s = suggest([tx(15, 1005)], [item("a", 15, 1000)], cfg)
    assert s[0].reason == "Diferença de R$ 0,05; no dia do vencimento"
    assert suggest([tx(15, 1006)], [item("a", 15, 1000)], cfg) == []
    assert suggest([tx(15, 995)], [item("a", 15, 1000)], cfg)
    assert suggest([tx(15, 1005)], [item("a", 15, 1000)]) == []


def test_days_wording():
    assert suggest([tx(10, 1000)], [item("a", 15, 1000)])[0].reason.endswith(
        "5 dias antes do vencimento"
    )
    assert suggest([tx(14, 1000)], [item("a", 15, 1000)])[0].reason.endswith(
        "1 dia antes do vencimento"
    )
    assert suggest([tx(25, 1000)], [item("a", 15, 1000)])[0].reason.endswith(
        "10 dias após o vencimento"
    )


def test_rejected_pair_not_suggested():
    t = tx(15, 1000, key="K")
    assert suggest([t], [item("a", 15, 1000)], rejected=frozenset({("K", "a")})) == []
    s = suggest([t], [item("a", 15, 1000), item("b", 15, 1000)], rejected=frozenset({("K", "a")}))
    assert [(x.item_id, x.is_primary) for x in s] == [("b", True)]


def test_cancelled_and_excluded_items_ignored():
    t = tx(15, 1000)
    assert suggest([t], [item("a", 15, 1000, status=ItemStatus.CANCELLED)]) == []
    assert suggest([t], [item("a", 15, 1000)], excluded_item_ids=frozenset({"a"})) == []


def test_item_used_once_globally():
    s = suggest([tx(15, 1000, key="k1"), tx(16, 1000, key="k2")], [item("a", 15, 1000)])
    assert [(x.transaction_key, x.is_primary) for x in primaries(s)] == [("k1", True)]
    demoted = [x for x in s if not x.is_primary]
    assert [(x.transaction_key, x.item_id, x.rule, x.score) for x in demoted] == [
        ("k2", "a", Rule.AMBIGUOUS, 99)
    ]
    assert demoted[0].reason == "Mesmo valor; 1 dia após o vencimento"


def test_conflict_tie_broken_by_date_then_key():
    s = suggest([tx(16, 1000, key="b"), tx(14, 1000, key="a")], [item("a", 15, 1000)])
    # mesmo score (99); a mais antiga vence
    assert [(x.transaction_key) for x in primaries(s)] == ["a"]


def test_higher_score_wins_conflict():
    s = suggest(
        [tx(17, 1000, key="far"), tx(15, 1000, key="near")],
        [item("a", 15, 1000)],
    )
    assert [x.transaction_key for x in primaries(s)] == ["near"]


def test_output_order_follows_input_then_score_then_item_id():
    s = suggest(
        [tx(15, 1000, key="t2"), tx(15, 2000, key="t1")],
        [item("z", 15, 1000), item("m", 15, 1000), item("a", 15, 2000)],
    )
    assert [(x.transaction_key, x.item_id) for x in s] == [("t2", "m"), ("t2", "z"), ("t1", "a")]


def test_config_validation():
    with pytest.raises(ValueError):
        MatchConfig(tolerance_cents=101)
    with pytest.raises(ValueError):
        MatchConfig(tolerance_cents=-1)
    with pytest.raises(ValueError):
        MatchConfig(days_before=-1)
    with pytest.raises(ValueError):
        MatchConfig(days_after=-1)
    assert MatchConfig() == MatchConfig(5, 10, 0)


def test_large_input_smoke():
    n = 3000
    txs = [tx(15, 1000 + i, key=f"k{i}") for i in range(n)]
    items = [item(f"i{i}", 15, 1000 + i) for i in range(n)]
    assert len(primaries(suggest(txs, items))) == n
    assert suggest(txs, items, MatchConfig(tolerance_cents=2))
