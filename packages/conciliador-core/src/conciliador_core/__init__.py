"""Conciliação financeira brasileira."""

from conciliador_core.dedup import deduplicate_transactions
from conciliador_core.engine import (
    BalanceCheck,
    ItemSituation,
    ItemState,
    MatchConfig,
    Rule,
    RuleBasedProvider,
    Suggestion,
    SuggestionProvider,
    check_balance,
    classify_item,
    find_probable_duplicates,
    has_gap,
)
from conciliador_core.errors import ParseError
from conciliador_core.models import (
    BankAccountRef,
    BankTransaction,
    Direction,
    ExpectedItem,
    ItemStatus,
    Source,
    Statement,
)
from conciliador_core.parsers import (
    CsvParseResult,
    FiscalParseResult,
    RowError,
    parse_fiscal_xml,
    parse_items_csv,
    parse_ofx,
    template_csv,
)

__version__ = "0.1.0"

__all__ = [
    "BalanceCheck",
    "BankAccountRef",
    "BankTransaction",
    "CsvParseResult",
    "Direction",
    "ExpectedItem",
    "FiscalParseResult",
    "ItemSituation",
    "ItemState",
    "ItemStatus",
    "MatchConfig",
    "ParseError",
    "RowError",
    "Rule",
    "RuleBasedProvider",
    "Source",
    "Statement",
    "Suggestion",
    "SuggestionProvider",
    "__version__",
    "check_balance",
    "classify_item",
    "deduplicate_transactions",
    "find_probable_duplicates",
    "has_gap",
    "parse_fiscal_xml",
    "parse_items_csv",
    "parse_ofx",
    "template_csv",
]
