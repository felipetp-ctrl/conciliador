import conciliador_core

EXPECTED = [
    "parse_ofx",
    "parse_fiscal_xml",
    "parse_items_csv",
    "template_csv",
    "deduplicate_transactions",
    "RuleBasedProvider",
    "MatchConfig",
    "Suggestion",
    "Rule",
    "find_probable_duplicates",
    "classify_item",
    "check_balance",
    "has_gap",
    "ParseError",
    "BankAccountRef",
    "BankTransaction",
    "Statement",
    "ExpectedItem",
    "Direction",
    "Source",
    "ItemStatus",
]


def test_public_api_exports():
    for name in EXPECTED:
        assert hasattr(conciliador_core, name), name
        assert name in conciliador_core.__all__, name


def test_all_names_resolve_and_version():
    for name in conciliador_core.__all__:
        assert hasattr(conciliador_core, name), name
    assert conciliador_core.__version__ == "0.1.0"
