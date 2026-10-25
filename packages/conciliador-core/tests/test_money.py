import pytest
from conciliador_core.errors import ParseError
from conciliador_core.money import parse_brl_amount


@pytest.mark.parametrize(
    ("text", "cents"),
    [
        ("1.234,56", 123456),
        ("1234.56", 123456),
        ("-10,00", -1000),
        ("0,5", 50),
        ("  99 ", 9900),
        ("-1,234.56", -123456),
        ("1.234", 123400),
        ("1.234.567", 123456700),
        ("+5,00", 500),
    ],
)
def test_parse_brl_amount(text: str, cents: int) -> None:
    assert parse_brl_amount(text) == cents


@pytest.mark.parametrize(
    "bad", ["", "abc", "1,2,3", "1.234,567", "NaN", "1e5", ",5", "1 234,56", "-", "12.34.567,89"]
)
def test_parse_brl_amount_rejects(bad: str) -> None:
    with pytest.raises(ParseError) as e:
        parse_brl_amount(bad)
    assert e.value.code == "invalid_amount"
    assert e.value.message


def test_parse_error_str() -> None:
    err = ParseError("too_large", "Arquivo grande demais.")
    assert err.code == "too_large"
    assert str(err) == "Arquivo grande demais."
