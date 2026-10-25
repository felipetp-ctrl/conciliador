from datetime import date

from conciliador_core.dedup import compute_dedup_keys, deduplicate_transactions
from conciliador_core.models import BankAccountRef, BankTransaction
from conciliador_core.parsers import parse_ofx
from conciliador_synth.ofx import SynthTxn, make_ofx

ACC = BankAccountRef("0341", "1234", "56789-0")
D = date(2026, 10, 5)


def _tx(fitid, key, memo="X", day=D, amount=100):
    return BankTransaction(fitid, day, amount, memo, (), key)


def test_identical_same_day_kept_as_two():
    tx = SynthTxn(date(2026, 10, 5), 5000, "PIX RECEBIDO FULANO")
    st = parse_ofx(make_ofx([tx, tx]))
    assert len({t.dedup_key for t in st.transactions}) == 2
    assert len(deduplicate_transactions([], st.transactions)) == 2


def test_reimport_with_unstable_fitid_is_deduplicated():
    a = parse_ofx(make_ofx([SynthTxn(date(2026, 10, 5), 5000, "PIX X", "AAA")]))
    b = parse_ofx(make_ofx([SynthTxn(date(2026, 10, 5), 5000, "pix  x", "BBB")]))
    assert deduplicate_transactions(a.transactions, b.transactions) == []


def test_same_fitid_is_duplicate_even_if_memo_changed():
    a = parse_ofx(make_ofx([SynthTxn(date(2026, 10, 5), 5000, "PIX X", "AAA")]))
    b = parse_ofx(make_ofx([SynthTxn(date(2026, 10, 5), 5000, "PIX Y", "AAA")]))
    assert deduplicate_transactions(a.transactions, b.transactions) == []


def test_overlapping_statements_keep_only_new():
    t1, t2 = SynthTxn(date(2026, 10, 1), 100, "A"), SynthTxn(date(2026, 10, 2), 200, "B")
    a = parse_ofx(make_ofx([t1]))
    b = parse_ofx(make_ofx([t1, t2]))
    new = deduplicate_transactions(a.transactions, b.transactions)
    assert [t.amount_cents for t in new] == [200]


def test_memo_normalization_accents_case_spaces():
    [a] = compute_dedup_keys(ACC, [(D, 100, "Pagamento  João")])
    [b] = compute_dedup_keys(ACC, [(D, 100, " PAGAMENTO JOAO ")])
    assert a == b


def test_pipe_in_memo_cannot_collide_with_other_field_split():
    acc1 = BankAccountRef("0341", "1234", "56789-0")
    acc2 = BankAccountRef("0341", "1234|56789-0", "")
    [k1] = compute_dedup_keys(acc1, [(D, 100, "A")])
    [k2] = compute_dedup_keys(acc2, [(D, 100, "A")])
    assert k1 != k2
    [m1] = compute_dedup_keys(ACC, [(D, 100, "A|1")])
    [m2] = compute_dedup_keys(ACC, [(D, 100, "A")])
    assert m1 != m2
    [n1] = compute_dedup_keys(ACC, [(D, 10, "0|X")])
    [n2] = compute_dedup_keys(ACC, [(D, 100, "X")])
    assert n1 != n2


def test_none_branch_differs_from_other_branch_and_is_stable():
    none = BankAccountRef("0341", None, "9")
    [a] = compute_dedup_keys(none, [(D, 1, "A")])
    [b] = compute_dedup_keys(BankAccountRef("0341", "", "9"), [(D, 1, "A")])
    assert a == b
    assert len(a) == 64


def test_ordinal_counts_only_identical_triples():
    keys = compute_dedup_keys(ACC, [(D, 1, "A"), (D, 1, "B"), (D, 1, "A")])
    assert len(set(keys)) == 3


def test_empty_fitid_counts_as_absent():
    existing = [_tx("", "k1")]
    incoming = [_tx("", "k2", memo="Y")]
    assert deduplicate_transactions(existing, incoming) == incoming


def test_duplicate_by_key_and_order_preserved():
    existing = [_tx("A", "k1")]
    incoming = [_tx("N1", "k9"), _tx("Z", "k1"), _tx("N2", "k8")]
    out = deduplicate_transactions(existing, incoming)
    assert [t.fitid for t in out] == ["N1", "N2"]


def test_incoming_not_deduplicated_against_itself():
    a = _tx("S", "k1")
    assert len(deduplicate_transactions([], [a, a])) == 2
