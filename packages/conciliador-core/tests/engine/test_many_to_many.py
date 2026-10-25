from datetime import date

from conciliador_core.engine.config import MatchConfig
from conciliador_core.engine.many_to_many import GroupSuggestion, find_group_suggestions
from conciliador_core.models import BankTransaction, Direction, ExpectedItem, ItemStatus, Source

DOC = "45723174000110"


def tx(key: str, cents: int, on: date = date(2026, 10, 20)) -> BankTransaction:
    return BankTransaction(
        fitid=None,
        posted_on=on,
        amount_cents=cents,
        memo=f"PIX {DOC}",
        documents=(DOC,),
        dedup_key=key,
    )


def item(id_: str, cents: int, due: date = date(2026, 10, 20)) -> ExpectedItem:
    return ExpectedItem(
        id=id_,
        source=Source.NFE,
        direction=Direction.INFLOW,
        amount_cents=cents,
        due_on=due,
        issued_on=due,
        counterpart_doc=DOC,
        counterpart_name="Cliente",
        document_number="47450",
        status=ItemStatus.OPEN,
    )


def test_partial_two_payments_close_one_title() -> None:
    cfg = MatchConfig()
    got = find_group_suggestions([tx("k1", 40000), tx("k2", 60000)], [item("i1", 100000)], cfg)
    assert got == [
        GroupSuggestion(
            "partial", ("k1", "k2"), ("i1",), "Título quitado em 2 lançamentos; a soma confere"
        )
    ]


def test_partial_requires_three_parts_when_two_dont_sum() -> None:
    cfg = MatchConfig()
    got = find_group_suggestions(
        [tx("k1", 30000), tx("k2", 30000), tx("k3", 40000)], [item("i1", 100000)], cfg
    )
    assert len(got) == 1
    assert got[0].kind == "partial"
    assert got[0].transaction_keys == ("k1", "k2", "k3")


def test_batch_one_payment_closes_many_titles() -> None:
    cfg = MatchConfig()
    got = find_group_suggestions([tx("k1", 100000)], [item("i1", 40000), item("i2", 60000)], cfg)
    assert got == [
        GroupSuggestion(
            "batch", ("k1",), ("i1", "i2"), "Remessa: 2 títulos num lançamento; a soma confere"
        )
    ]


def test_ambiguous_group_is_not_emitted() -> None:
    cfg = MatchConfig()
    # 40+60 e 50+50 fecham 100: empate → não decide sozinho.
    got = find_group_suggestions(
        [tx("k1", 40000), tx("k2", 60000), tx("k3", 50000), tx("k4", 50000)],
        [item("i1", 100000)],
        cfg,
    )
    assert got == []


def test_no_signal_means_no_suggestion() -> None:
    cfg = MatchConfig()
    no_doc = BankTransaction(
        fitid=None,
        posted_on=date(2026, 10, 20),
        amount_cents=40000,
        memo="PIX SEM CNPJ",
        documents=(),
        dedup_key="k1",
    )
    no_doc2 = BankTransaction(
        fitid=None,
        posted_on=date(2026, 10, 20),
        amount_cents=60000,
        memo="PIX SEM CNPJ",
        documents=(),
        dedup_key="k2",
    )
    assert find_group_suggestions([no_doc, no_doc2], [item("i1", 100000)], cfg) == []


def test_parts_do_not_overlap() -> None:
    cfg = MatchConfig()
    got = find_group_suggestions(
        [tx("k1", 40000), tx("k2", 60000), tx("k3", 100000)],
        [item("i1", 100000), item("i2", 100000)],
        cfg,
    )
    # i1 = k1+k2 (partial) e i2 = k3 ficaria sem par (1:1 já teria pego k3; aqui k3 sobra)
    assert len(got) == 1
    assert got[0].transaction_keys == ("k1", "k2")
