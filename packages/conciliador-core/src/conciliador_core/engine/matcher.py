"""Conciliação por regras: gera sugestões que uma pessoa confirma."""

import re
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import timedelta
from enum import StrEnum
from typing import Protocol

from conciliador_core.documents import document_spans
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
    """Gera sugestões de vínculo para uma pessoa confirmar.

    ``rejected``: pares ``(transaction_key, item_id)`` que a pessoa recusou.
    ``excluded_item_ids``: itens que a pessoa **removeu ou mesclou** (deixaram de existir para
    a conciliação). **Não** é para duplicatas prováveis (``find_probable_duplicates``): enquanto
    não resolvidas, elas já viram ``AMBIGUOUS`` naturalmente quando empatam e precisam continuar
    vinculáveis por ``DOCUMENT``/``NUMBER``; excluí-las esconderia o item certo.
    """

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
# Datas no histórico (dd/mm/aaaa, dd-mm-aaaa, aaaa-mm-dd, mm/aaaa, dd/mm): seus dígitos
# nunca são nº de documento ("REF 10/2026" não cita a nota nº 10).
_DATE = re.compile(
    r"(?<![0-9])(?:"
    r"[0-9]{1,2}([/-])[0-9]{1,2}\1[0-9]{4}"
    r"|[0-9]{4}-[0-9]{1,2}-[0-9]{1,2}"
    r"|[0-9]{1,2}/[0-9]{4}"
    r"|[0-9]{1,2}/[0-9]{1,2}"
    r")(?![0-9])"
)
_MIN_NUMBER_DIGITS = 3


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


def _number_key(number: str | None) -> str | None:
    """Só os dígitos do nº do documento, sem zeros à esquerda ("NF-1001" vira "1001").

    Nºs com menos de 3 dígitos significativos não contam: casam com qualquer dia, mês ou
    parcela citados no histórico.
    """
    if number is None:
        return None
    digits = "".join(_DIGITS.findall(number)).lstrip("0")
    return digits if len(digits) >= _MIN_NUMBER_DIGITS else None


def _memo_numbers(memo: str) -> frozenset[str]:
    """Sequências máximas de dígitos ASCII do histórico, sem zeros à esquerda, exceto as que
    fazem parte de uma data ou de um CPF/CNPJ válido."""
    blocked = [m.span() for m in _DATE.finditer(memo)]
    blocked += [(start, end) for start, end, _ in document_spans(memo)]
    tokens: set[str] = set()
    for match in _DIGITS.finditer(memo):
        start, end = match.span()
        if any(start < b_end and end > b_start for b_start, b_end in blocked):
            continue
        token = match.group().lstrip("0")
        if token:
            tokens.add(token)
    return frozenset(tokens)


class RuleBasedProvider:
    """Regras em ordem de força: ``DOCUMENT`` (CPF/CNPJ do item no histórico), ``NUMBER``
    (nº do documento no histórico) e ``UNIQUE`` (único candidato por valor e janela).

    Veja :class:`SuggestionProvider` sobre ``rejected`` e ``excluded_item_ids`` (este último
    não serve para duplicatas prováveis).
    """

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
    tokens = _memo_numbers(t.memo)
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
        elif (number := _number_key(item.document_number)) is not None and number in tokens:
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
