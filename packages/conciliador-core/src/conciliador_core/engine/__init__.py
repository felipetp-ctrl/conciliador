"""Motor de conciliação: gera sugestões de vínculo entre lançamentos e itens esperados."""

from conciliador_core.engine.config import MatchConfig
from conciliador_core.engine.matcher import Rule, RuleBasedProvider, Suggestion, SuggestionProvider

__all__ = ["MatchConfig", "Rule", "RuleBasedProvider", "Suggestion", "SuggestionProvider"]
