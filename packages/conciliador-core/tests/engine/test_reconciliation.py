from conciliador_core.engine.reconciliation import (
    BankReconciliation,
    LedgerLine,
    reconcile_balances,
)
from conciliador_core.models import Direction

IN = Direction.INFLOW
OUT = Direction.OUTFLOW


def settled(id_: str, direction: Direction, cents: int) -> LedgerLine:
    return LedgerLine(id_, direction, cents, "settled")


def classified(id_: str, direction: Direction, cents: int) -> LedgerLine:
    return LedgerLine(id_, direction, cents, "classified")


def test_everything_reconciled_balances() -> None:
    # extrato: +5000, -2000; controle: baixas iguais. Nada sem explicação.
    res = reconcile_balances(
        opening_cents=1000,
        statement_inflows=5000,
        statement_outflows=2000,
        statement_closing_cents=4000,
        ledger_lines=[settled("a", IN, 5000), settled("b", OUT, 2000)],
        value_gap_cents=0,
        unexplained_cents=0,
    )
    assert res.balanced is True
    assert res.consistent is True
    assert res.statement_consistent is True
    assert res.ledger_closing_cents == 4000


def test_unexplained_is_exactly_the_difference() -> None:
    # o extrato tem um crédito de 950 sem documento: a diferença é exatamente -950.
    res = reconcile_balances(
        opening_cents=1000,
        statement_inflows=5000,
        statement_outflows=2000,
        statement_closing_cents=4000,
        ledger_lines=[settled("a", IN, 4050), settled("b", OUT, 2000)],
        value_gap_cents=0,
        unexplained_cents=950,
    )
    assert res.difference_cents == -950
    assert res.consistent is True
    assert res.balanced is False


def test_value_gap_is_part_of_the_explanation() -> None:
    # título de 389,90 (OUT) baixado por 408,40 no banco: o banco pagou 18,50 a mais.
    # gap assinado = documento − extrato = (-38990) − (-40840) = +1850.
    res = reconcile_balances(
        opening_cents=0,
        statement_inflows=0,
        statement_outflows=40840,
        statement_closing_cents=-40840,
        ledger_lines=[settled("a", OUT, 38990)],
        value_gap_cents=1850,
        unexplained_cents=0,
    )
    # razão: -38990; extrato: -40840; diferença = +1850
    assert res.difference_cents == 1850
    assert res.consistent is True


def test_inconsistent_when_partition_is_wrong() -> None:
    # passam uma soma "sem explicação" que não bate com a diferença real.
    res = reconcile_balances(
        opening_cents=0,
        statement_inflows=5000,
        statement_outflows=0,
        statement_closing_cents=5000,
        ledger_lines=[],
        value_gap_cents=0,
        unexplained_cents=100,  # errado: deveria ser 5000
    )
    assert res.consistent is False
    assert res.difference_cents == -5000


def test_statement_consistency_unknown_without_opening() -> None:
    res = reconcile_balances(
        opening_cents=None,
        statement_inflows=5000,
        statement_outflows=0,
        statement_closing_cents=5000,
        ledger_lines=[],
        value_gap_cents=0,
        unexplained_cents=5000,
    )
    assert res.statement_consistent is None
    assert res.ledger_closing_cents is None


def test_statement_does_not_close() -> None:
    res = reconcile_balances(
        opening_cents=1000,
        statement_inflows=5000,
        statement_outflows=2000,
        statement_closing_cents=3999,  # não bate com 1000+5000-2000
        ledger_lines=[],
        value_gap_cents=0,
        unexplained_cents=0,
    )
    assert res.statement_consistent is False


def test_dataclass_shape() -> None:
    res = reconcile_balances(
        opening_cents=0,
        statement_inflows=10,
        statement_outflows=3,
        statement_closing_cents=7,
        ledger_lines=[],
        value_gap_cents=0,
        unexplained_cents=7,
    )
    assert isinstance(res, BankReconciliation)
    assert res.statement_movement_cents == 7
    assert res.ledger_movement_cents == 0
