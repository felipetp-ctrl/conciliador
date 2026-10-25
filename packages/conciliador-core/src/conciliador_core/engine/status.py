"""Situação de um item esperado: quitado, pendente, vencido ou cancelado."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from conciliador_core.models import ExpectedItem, ItemStatus


class ItemState(StrEnum):
    SETTLED = "settled"
    PENDING = "pending"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ItemSituation:
    """``remaining_cents``: quanto falta; ``excess_cents``: quanto foi pago a mais (vínculos
    acima do valor do item). Pagamento a maior continua ``SETTLED``."""

    state: ItemState
    remaining_cents: int
    excess_cents: int


def classify_item(
    item: ExpectedItem, linked_cents: int, closed_with_difference: bool, today: date
) -> ItemSituation:
    if linked_cents < 0:
        raise ValueError("linked_cents não pode ser negativo")
    if item.status is ItemStatus.CANCELLED:
        return ItemSituation(ItemState.CANCELLED, 0, 0)
    excess = max(linked_cents - item.amount_cents, 0)
    if closed_with_difference or linked_cents >= item.amount_cents:
        return ItemSituation(ItemState.SETTLED, 0, excess)
    remaining = item.amount_cents - linked_cents
    state = ItemState.OVERDUE if today > item.due_on else ItemState.PENDING
    return ItemSituation(state, remaining, 0)
