"""Duplicatas prováveis entre origens diferentes (ex.: NF e planilha do mesmo título)."""

from collections import defaultdict
from collections.abc import Sequence
from itertools import combinations

from conciliador_core.models import Direction, ExpectedItem, ItemStatus

_MAX_DAYS_APART = 5


def _number(item: ExpectedItem) -> str:
    """Número do documento sem zeros à esquerda; vazio nunca conta como igual."""
    return (item.document_number or "").strip().lstrip("0")


def _is_duplicate(a: ExpectedItem, b: ExpectedItem) -> bool:
    if a.source == b.source:
        return False
    if a.counterpart_doc and b.counterpart_doc and a.counterpart_doc != b.counterpart_doc:
        return False
    if abs((a.due_on - b.due_on).days) <= _MAX_DAYS_APART:
        return True
    number = _number(a)
    return bool(number) and number == _number(b)


def find_probable_duplicates(items: Sequence[ExpectedItem]) -> list[tuple[str, str]]:
    """Pares (id_a, id_b), id_a < id_b, ordenados e sem repetição."""
    groups: dict[tuple[Direction, int], list[ExpectedItem]] = defaultdict(list)
    for item in items:
        if item.status is not ItemStatus.CANCELLED:
            groups[(item.direction, item.amount_cents)].append(item)
    pairs: set[tuple[str, str]] = set()
    for group in groups.values():
        for a, b in combinations(group, 2):
            if a.id != b.id and _is_duplicate(a, b):
                pairs.add((min(a.id, b.id), max(a.id, b.id)))
    return sorted(pairs)
