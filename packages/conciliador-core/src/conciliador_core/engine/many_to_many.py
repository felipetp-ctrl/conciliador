"""Casamento N:N enxuto: um título quitado em parcelas e uma remessa com vários títulos.

Roda **depois** das sugestões 1:1 (``RuleBasedProvider``): pega os lançamentos e itens que
sobraram e procura combinações de 2 ou 3 partes cuja soma fecha o valor (dentro da
tolerância). Só emite sugestão quando a combinação é **única** — se houver mais de uma, deixa
para a pessoa decidir manualmente (nada é decidido no lugar dela).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from itertools import combinations
from typing import Literal

from conciliador_core.engine.config import MatchConfig
from conciliador_core.engine.matcher import _memo_numbers, _number_key
from conciliador_core.models import BankTransaction, ExpectedItem

MAX_PARTS = 3


@dataclass(frozen=True)
class GroupSuggestion:
    """Um grupo banco ⟷ documentos com mais de uma parte em um dos lados."""

    kind: Literal["partial", "batch"]
    transaction_keys: tuple[str, ...]
    item_ids: tuple[str, ...]
    reason: str


def _signals(txn: BankTransaction, item: ExpectedItem, config: MatchConfig) -> bool:
    """O lançamento aponta para o item: mesma direção, dentro da janela e com sinal no histórico."""
    if txn.amount_cents == 0 or txn.direction != item.direction:
        return False
    if not (
        item.due_on - timedelta(days=config.days_before)
        <= txn.posted_on
        <= item.due_on + timedelta(days=config.days_after)
    ):
        return False
    if item.counterpart_doc is not None and item.counterpart_doc in txn.documents:
        return True
    number = _number_key(item.document_number)
    return number is not None and number in _memo_numbers(txn.memo)


def _combos_by_sum(amounts: Sequence[int], target: int, tolerance: int) -> list[tuple[int, ...]]:
    """Índices das combinações de 2..``MAX_PARTS`` cuja soma bate o alvo (dentro da tolerância)."""
    found: list[tuple[int, ...]] = []
    for k in range(2, MAX_PARTS + 1):
        for idxs in combinations(range(len(amounts)), k):
            if abs(sum(amounts[i] for i in idxs) - target) <= tolerance:
                found.append(idxs)
    return found


def find_group_suggestions(
    leftover_txns: Sequence[BankTransaction],
    leftover_items: Sequence[ExpectedItem],
    config: MatchConfig,
) -> list[GroupSuggestion]:
    """Gera sugestões ``partial`` e ``batch`` a partir das sobras 1:1 (sem sobreposição)."""
    txns = list(leftover_txns)
    items = list(leftover_items)
    tolerance = config.tolerance_cents
    used_tx_keys: set[str] = set()
    used_item_ids: set[str] = set()
    out: list[GroupSuggestion] = []

    # partial: N lançamentos quitam 1 título
    for item in items:
        if item.id in used_item_ids:
            continue
        tx_members = [
            t
            for t in txns
            if t.dedup_key not in used_tx_keys
            and abs(t.amount_cents) < item.amount_cents
            and _signals(t, item, config)
        ]
        matches = _combos_by_sum(
            [abs(t.amount_cents) for t in tx_members], item.amount_cents, tolerance
        )
        if len(matches) == 1:
            tx_combo = [tx_members[i] for i in matches[0]]
            out.append(
                GroupSuggestion(
                    "partial",
                    tuple(t.dedup_key for t in tx_combo),
                    (item.id,),
                    f"Título quitado em {len(tx_combo)} lançamentos; a soma confere",
                )
            )
            used_item_ids.add(item.id)
            used_tx_keys.update(t.dedup_key for t in tx_combo)

    # batch: 1 lançamento quita N títulos
    for txn in txns:
        if txn.dedup_key in used_tx_keys:
            continue
        amount = abs(txn.amount_cents)
        item_members = [
            i
            for i in items
            if i.id not in used_item_ids and i.amount_cents < amount and _signals(txn, i, config)
        ]
        matches = _combos_by_sum([i.amount_cents for i in item_members], amount, tolerance)
        if len(matches) == 1:
            item_combo = [item_members[i] for i in matches[0]]
            out.append(
                GroupSuggestion(
                    "batch",
                    (txn.dedup_key,),
                    tuple(i.id for i in item_combo),
                    f"Remessa: {len(item_combo)} títulos num lançamento; a soma confere",
                )
            )
            used_tx_keys.add(txn.dedup_key)
            used_item_ids.update(i.id for i in item_combo)

    return out
