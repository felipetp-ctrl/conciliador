"""Motor de conciliação: gera sugestões de vínculo entre lançamentos e itens esperados."""

from conciliador_core.engine.balance import BalanceCheck, check_balance, has_gap
from conciliador_core.engine.config import MatchConfig
from conciliador_core.engine.duplicates import find_probable_duplicates
from conciliador_core.engine.matcher import Rule, RuleBasedProvider, Suggestion, SuggestionProvider
from conciliador_core.engine.status import ItemSituation, ItemState, classify_item

__all__ = [
    "BalanceCheck",
    "ItemSituation",
    "ItemState",
    "MatchConfig",
    "Rule",
    "RuleBasedProvider",
    "Suggestion",
    "SuggestionProvider",
    "check_balance",
    "classify_item",
    "find_probable_duplicates",
    "has_gap",
]
