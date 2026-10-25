"""Conciliação por regras: gera sugestões que uma pessoa confirma."""

import re
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import timedelta
from enum import StrEnum
from typing import Protocol

from conciliador_core.engine.config import MatchConfig
from conciliador_core.models import BankTransaction, Direction, ExpectedItem, ItemStatus


class Rule(StrEnum):
    DOCUMENT = "document"
    NUMBER = "number"
    UNIQUE = "unique"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class Suggestion:
    transaction_key: str
    item_id: str
    rule: Rule
    score: int
    reason: str
    is_primary: bool


class SuggestionProvider(Protocol):
    def suggest(
        self,
        transactions: Sequence[BankTransaction],
        items: Sequence[ExpectedItem],
        config: MatchConfig,
        *,
        rejected: frozenset[tuple[str, str]] = frozenset(),
        excluded_item_ids: frozenset[str] = frozenset(),
    ) -> list[Suggestion]: ...


_BASE_SCORE = {Rule.DOCUMENT: 300, Rule.NUMBER: 200, Rule.UNIQUE: 100}
_STRENGTH = (Rule.DOCUMENT, Rule.NUMBER, Rule.UNIQUE)
_DIGITS = re.compile(r"[0-9]+")


@dataclass(frozen=True)
class _Candidate:
    item: ExpectedItem
    rule: Rule
    score: int
    reason: str


def _money(cents: int) -> str:
    return f"R$ {cents // 100},{cents % 100:02d}"


def _days_text(delta: int) -> str:
    if delta == 0:
        return "no dia do vencimento"
    n = abs(delta)
    unit = "dia" if n == 1 else "dias"
    side = "após" if delta > 0 else "antes"
    return f"{n} {unit} {side} {'o' if delta > 0 else 'do'} vencimento"


def _reason(diff: int, rule: Rule, delta: int) -> str:
    parts = ["Mesmo valor" if diff == 0 else f"Diferença de {_money(diff)}"]
    if rule is Rule.DOCUMENT:
        parts.append("CPF/CNPJ no histórico")
    elif rule is Rule.NUMBER:
        parts.append("Nº do documento no histórico")
    parts.append(_days_text(delta))
    return "; ".join(parts)


def _strip_zeros(value: str) -> str:
    return value.lstrip("0")


class RuleBasedProvider:
    def suggest(
        self,
        transactions: Sequence[BankTransaction],
        items: Sequence[ExpectedItem],
        config: MatchConfig,
        *,
        rejected: frozenset[tuple[str, str]] = frozenset(),
        excluded_item_ids: frozenset[str] = frozenset(),
    ) -> list[Suggestion]:
        index = _build_index(items, excluded_item_ids)

        # por transação: (candidatos devolvidos, é primária?)
        per_tx: list[list[_Candidate]] = []
        primary_of: dict[int, _Candidate] = {}
        for pos, t in enumerate(transactions):
            chosen, is_primary = _decide(_candidates(t, index, config, rejected))
            per_tx.append(chosen)
            if is_primary:
                primary_of[pos] = chosen[0]

        # conflito global: o item vai para a principal de maior score
        order = sorted(
            primary_of,
            key=lambda p: (
                -primary_of[p].score,
                transactions[p].posted_on,
                transactions[p].dedup_key,
                p,
            ),
        )
        taken: set[str] = set()
        demoted: set[int] = set()
        for pos in order:
            item_id = primary_of[pos].item.id
            if item_id in taken:
                demoted.add(pos)
            else:
                taken.add(item_id)

        result: list[Suggestion] = []
        for pos, chosen in enumerate(per_tx):
            key = transactions[pos].dedup_key
            is_primary = pos in primary_of and pos not in demoted
            suggestions = [
                Suggestion(
                    key,
                    c.item.id,
                    c.rule if is_primary else Rule.AMBIGUOUS,
                    c.score,
                    c.reason,
                    is_primary,
                )
                for c in chosen
            ]
            suggestions.sort(key=lambda s: (-s.score, s.item_id))
            result.extend(suggestions)
        return result


class _Index:
    """Itens abertos por direção, ordenados por valor, para busca por faixa."""

    def __init__(self) -> None:
        self.amounts: dict[Direction, list[int]] = {}
        self.items: dict[Direction, list[ExpectedItem]] = {}


def _build_index(items: Sequence[ExpectedItem], excluded: frozenset[str]) -> _Index:
    index = _Index()
    usable = [i for i in items if i.status is ItemStatus.OPEN and i.id not in excluded]
    usable.sort(key=lambda i: i.amount_cents)
    for direction in Direction:
        subset = [i for i in usable if i.direction is direction]
        index.items[direction] = subset
        index.amounts[direction] = [i.amount_cents for i in subset]
    return index


def _candidates(
    t: BankTransaction,
    index: _Index,
    config: MatchConfig,
    rejected: frozenset[tuple[str, str]],
) -> list[_Candidate]:
    if t.amount_cents == 0:
        return []
    amount = abs(t.amount_cents)
    amounts = index.amounts[t.direction]
    lo = bisect_left(amounts, amount - config.tolerance_cents)
    hi = bisect_right(amounts, amount + config.tolerance_cents)
    tokens = {_strip_zeros(x) for x in _DIGITS.findall(t.memo)} - {""}
    found: list[_Candidate] = []
    for item in index.items[t.direction][lo:hi]:
        if (t.dedup_key, item.id) in rejected:
            continue
        if not (
            item.due_on - timedelta(days=config.days_before)
            <= t.posted_on
            <= item.due_on + timedelta(days=config.days_after)
        ):
            continue
        delta = (t.posted_on - item.due_on).days
        if item.counterpart_doc is not None and item.counterpart_doc in t.documents:
            rule = Rule.DOCUMENT
        elif item.document_number is not None and _strip_zeros(item.document_number) in tokens:
            rule = Rule.NUMBER
        else:
            rule = Rule.UNIQUE
        diff = abs(amount - item.amount_cents)
        found.append(
            _Candidate(item, rule, _BASE_SCORE[rule] - abs(delta), _reason(diff, rule, delta))
        )
    return found


def _decide(found: list[_Candidate]) -> tuple[list[_Candidate], bool]:
    """Devolve os candidatos a emitir e se o primeiro é a sugestão principal."""
    for rule in _STRENGTH:
        top = [c for c in found if c.rule is rule]
        if not top:
            continue
        if len(top) == 1 and (rule is not Rule.UNIQUE or len(found) == 1):
            return top, True
        return [replace(c, rule=Rule.AMBIGUOUS) for c in top], False
    return [], False
