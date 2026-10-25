"""Conciliação bancária de saldo: a razão derivada dos documentos contra o extrato.

Esta é a camada clássica da conciliação bancária: dois saldos independentes e a diferença
**explicada**. O lado "razão" (controle interno) não vem de um plano de contas — para uma
pequena empresa ele é o que os documentos dizem: as baixas confirmadas mais os lançamentos
do extrato que foram classificados (tarifa, rendimento, etc.). Transferências entre contas
não entram em nenhum dos dois saldos.

A prova da conciliação é a identidade::

    saldo_razão − saldo_extrato == diferença_de_valor_das_baixas − sem_explicação

Ou seja, a diferença entre os saldos é exatamente o que ainda não tem explicação (os
lançamentos do extrato sem documento nem classificação) somado às baixas quitadas com valor
diferente do documento. Se essa identidade não fechar, algum lançamento ficou fora da
partição — e o produto precisa apontar isso, não esconder.

Convenção de sinal (todos em centavos inteiros):

- ``value_gap_cents`` = soma de (documento assinado − extrato assinado) por baixa.
- ``unexplained_cents`` = soma assinada dos lançamentos do extrato sem documento/classificação
  (crédito positivo, débito negativo).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from conciliador_core.models import Direction


@dataclass(frozen=True)
class LedgerLine:
    """Uma parcela do controle interno: baixa confirmada ou lançamento classificado.

    ``amount_cents`` é sempre positivo; o sinal vem de ``direction``.
    """

    id: str
    direction: Direction
    amount_cents: int
    kind: Literal["settled", "classified"]

    def __post_init__(self) -> None:
        if self.amount_cents < 0:
            raise ValueError("amount_cents deve ser positivo (centavos inteiros)")


@dataclass(frozen=True)
class BankReconciliation:
    """Dois saldos e a explicação da diferença."""

    opening_cents: int | None
    # Extrato (o que o banco registrou)
    statement_inflows: int
    statement_outflows: int
    statement_closing_cents: int | None
    # Controle interno (o que os documentos dizem)
    ledger_inflows: int
    ledger_outflows: int
    # Diferença e a sua explicação
    difference_cents: int
    unexplained_cents: int  # soma assinada (créditos +, débitos −) sem documento/classificação
    value_gap_cents: int  # soma assinada de (documento − extrato) nas baixas
    # Verificações
    statement_consistent: bool | None  # saldo inicial + movimento == LEDGERBAL (se ambos)
    balanced: bool

    @property
    def statement_movement_cents(self) -> int:
        return self.statement_inflows - self.statement_outflows

    @property
    def ledger_movement_cents(self) -> int:
        return self.ledger_inflows - self.ledger_outflows

    @property
    def ledger_closing_cents(self) -> int | None:
        if self.opening_cents is None:
            return None
        return self.opening_cents + self.ledger_movement_cents

    @property
    def consistent(self) -> bool:
        """A diferença é exatamente o que falta explicar mais as diferenças de valor."""
        return self.difference_cents == self.value_gap_cents - self.unexplained_cents


def reconcile_balances(
    *,
    opening_cents: int | None,
    statement_inflows: int,
    statement_outflows: int,
    statement_closing_cents: int | None,
    ledger_lines: Sequence[LedgerLine],
    value_gap_cents: int,
    unexplained_cents: int,
) -> BankReconciliation:
    """Monta a conciliação bancária de um período/uma conta.

    ``unexplained_cents`` e ``value_gap_cents`` entram **assinados**: crédito/receber positivo,
    débito/pagar negativo. ``value_gap_cents`` é ``documento − extrato`` por baixa.
    """
    ledger_inflows = sum(
        line.amount_cents for line in ledger_lines if line.direction is Direction.INFLOW
    )
    ledger_outflows = sum(
        line.amount_cents for line in ledger_lines if line.direction is Direction.OUTFLOW
    )
    difference = (ledger_inflows - ledger_outflows) - (statement_inflows - statement_outflows)

    if opening_cents is not None and statement_closing_cents is not None:
        statement_consistent = opening_cents + statement_inflows - statement_outflows == (
            statement_closing_cents
        )
    else:
        statement_consistent = None

    return BankReconciliation(
        opening_cents=opening_cents,
        statement_inflows=statement_inflows,
        statement_outflows=statement_outflows,
        statement_closing_cents=statement_closing_cents,
        ledger_inflows=ledger_inflows,
        ledger_outflows=ledger_outflows,
        difference_cents=difference,
        unexplained_cents=unexplained_cents,
        value_gap_cents=value_gap_cents,
        statement_consistent=statement_consistent,
        balanced=difference == 0,
    )
