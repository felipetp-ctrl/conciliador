from datetime import date
from pathlib import Path

import pytest
from conciliador_core.errors import ParseError
from conciliador_core.parsers import MAX_FILE_BYTES, parse_ofx
from conciliador_synth.ofx import SynthTxn, make_ofx

TX = [
    SynthTxn(date(2026, 10, 1), 123456, "PIX RECEBIDO 52998224725 JOSÉ", "F1"),
    SynthTxn(date(2026, 10, 2), -9990, "TARIFA PACOTE", "F2"),
]

CORPUS = Path(__file__).parent.parent / "corpus" / "ofx"

# Arquivos do corpus sem lançamentos (não são extratos com movimento):
#  - bank_small.ofx: apenas "<OFX></OFX>", sem extrato (deve dar ParseError).
#  - error_message.ofx: STATUS de erro (2000) no STMTTRNRS: invalid_format com o erro do banco.
#  - multiple_accounts.ofx: dois extratos no mesmo arquivo: unsupported_document.
NO_TRANSACTIONS = {"bank_small.ofx", "error_message.ofx", "multiple_accounts.ofx"}
CORPUS_FILES = sorted(p for p in CORPUS.glob("*.ofx") if p.name not in NO_TRANSACTIONS)


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("encoding", ["cp1252", "utf-8"])
@pytest.mark.parametrize("decimal_comma", [False, True])
def test_variants_parse_identically(version, encoding, decimal_comma):
    st = parse_ofx(
        make_ofx(
            TX,
            version=version,
            encoding=encoding,
            decimal_comma=decimal_comma,
            ledger_balance_cents=500000,
        )
    )
    assert [t.amount_cents for t in st.transactions] == [123456, -9990]
    assert st.transactions[0].memo == "PIX RECEBIDO 52998224725 JOSÉ"
    assert st.transactions[0].documents == ("52998224725",)
    assert st.transactions[0].fitid == "F1"
    assert st.transactions[0].posted_on == date(2026, 10, 1)
    assert len(st.transactions[0].dedup_key) == 64
    assert st.ledger_balance_cents == 500000
    assert st.account.bank_id == "0341"
    assert st.account.branch == "1234"
    assert st.account.account_number == "56789-0"
    assert st.start == date(2026, 10, 1) and st.end == date(2026, 10, 2)


def test_lying_charset_header_falls_back_to_cp1252():
    raw = make_ofx(TX, version=1, encoding="cp1252", declared_charset="USASCII")
    assert parse_ofx(raw).transactions[0].memo.endswith("JOSÉ")


def test_dtposted_with_timezone_suffix():
    raw = make_ofx(TX).replace(b"<DTPOSTED>20261001", b"<DTPOSTED>20261001120000[-3:BRT]", 1)
    assert parse_ofx(raw).transactions[0].posted_on == date(2026, 10, 1)


def test_missing_optionals():
    st = parse_ofx(make_ofx(TX, omit_optional=True))
    assert st.ledger_balance_cents is None and st.transactions[0].fitid is None
    assert st.start is None and st.end is None


def test_too_large():
    with pytest.raises(ParseError) as e:
        parse_ofx(b"x" * (MAX_FILE_BYTES + 1))
    assert e.value.code == "too_large"


def test_not_ofx():
    with pytest.raises(ParseError) as e:
        parse_ofx(b"%PDF-1.7 ...")
    assert e.value.code == "invalid_format"


@pytest.mark.parametrize("version", [1, 2])
def test_entities_unescaped_and_controls_stripped(version):
    memo = "A & B <C> \x01 x\t\ty\x7f"
    raw = make_ofx([SynthTxn(date(2026, 10, 1), 100, memo, "F")], version=version)
    assert parse_ofx(raw).transactions[0].memo == "A & B <C> x y"


def _with_name(raw: bytes, name: str) -> bytes:
    return raw.replace(b"<MEMO>TARIFA PACOTE", f"<NAME>{name}<MEMO>TARIFA PACOTE".encode(), 1)


def test_name_and_memo_joined():
    raw = _with_name(make_ofx(TX, version=1), "BANCO X")
    assert parse_ofx(raw).transactions[1].memo == "BANCO X TARIFA PACOTE"


def test_name_equal_to_memo_not_duplicated():
    raw = _with_name(make_ofx(TX, version=1), "TARIFA PACOTE")
    assert parse_ofx(raw).transactions[1].memo == "TARIFA PACOTE"


def test_name_only():
    raw = make_ofx(TX, version=1).replace(b"<MEMO>TARIFA PACOTE", b"<NAME>SO NOME", 1)
    assert parse_ofx(raw).transactions[1].memo == "SO NOME"


def test_malformed_amount_raises_invalid_amount():
    raw = make_ofx(TX).replace(b"<TRNAMT>1234.56", b"<TRNAMT>12abc", 1)
    with pytest.raises(ParseError) as e:
        parse_ofx(raw)
    assert e.value.code == "invalid_amount"


@pytest.mark.parametrize("bad", [b"<DTPOSTED>", b"<DTPOSTED>2026"])
def test_bad_date_raises_invalid_format(bad):
    raw = make_ofx(TX).replace(b"<DTPOSTED>20261001120000", bad, 1)
    with pytest.raises(ParseError) as e:
        parse_ofx(raw)
    assert e.value.code == "invalid_format"


def test_impossible_date():
    raw = make_ofx(TX).replace(b"<DTPOSTED>20261001", b"<DTPOSTED>20261301", 1)
    with pytest.raises(ParseError) as e:
        parse_ofx(raw)
    assert e.value.code == "invalid_format"


@pytest.mark.parametrize("path", CORPUS_FILES, ids=lambda p: p.name)
def test_corpus_parses_with_transactions(path):
    st = parse_ofx(path.read_bytes())
    assert len(st.transactions) >= 1


def test_corpus_credit_card_statement():
    st = parse_ofx((CORPUS / "anzcc.ofx").read_bytes())
    assert st.account.bank_id == "" and st.account.branch is None
    assert st.account.account_number == "1234123412341234"
    assert st.transactions[0].amount_cents == -550
    assert st.ledger_balance_cents == -12345


def test_corpus_empty_tags():
    st = parse_ofx((CORPUS / "ofx-v102-empty-tags.ofx").read_bytes())
    assert st.transactions[0].fitid is None
    assert st.transactions[0].memo == "CBA:Transfer"
    assert st.ledger_balance_cents is None
    assert st.account.branch is None


def test_corpus_without_statement_raises():
    with pytest.raises(ParseError) as e:
        parse_ofx((CORPUS / "bank_small.ofx").read_bytes())
    assert e.value.code == "invalid_format"


def test_corpus_bank_error_status_raises():
    with pytest.raises(ParseError) as e:
        parse_ofx((CORPUS / "error_message.ofx").read_bytes())
    assert e.value.code == "invalid_format"
    assert "erro" in e.value.message and "2000" in e.value.message
    assert "General Server Error" in e.value.message


def test_corpus_multiple_accounts_unsupported():
    with pytest.raises(ParseError) as e:
        parse_ofx((CORPUS / "multiple_accounts.ofx").read_bytes())
    assert e.value.code == "unsupported_document"
    assert e.value.message == ("O arquivo tem mais de uma conta; exporte uma conta por arquivo.")


def _card(raw: bytes) -> bytes:
    for old, new in [
        (b"BANKMSGSRSV1", b"CREDITCARDMSGSRSV1"),
        (b"STMTTRNRS", b"CCSTMTTRNRS"),
        (b"STMTRS", b"CCSTMTRS"),
        (b"BANKACCTFROM", b"CCACCTFROM"),
    ]:
        raw = raw.replace(old, new)
    return raw


def _block(raw: bytes, start: bytes, end: bytes) -> bytes:
    i = raw.index(start)
    return raw[i : raw.index(end, i) + len(end)]


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("second", ["bank", "card"])
def test_second_statement_is_unsupported(version, second):
    raw = make_ofx(TX, version=version)
    if second == "bank":
        extra = _block(raw, b"<STMTTRNRS>", b"</STMTTRNRS>")
        raw = raw.replace(b"</BANKMSGSRSV1>", extra + b"</BANKMSGSRSV1>")
    else:
        extra = _card(_block(raw, b"<BANKMSGSRSV1>", b"</BANKMSGSRSV1>"))
        raw = raw.replace(b"</OFX>", extra + b"</OFX>")
    with pytest.raises(ParseError) as e:
        parse_ofx(raw)
    assert e.value.code == "unsupported_document"
    assert "mais de uma conta" in e.value.message


def test_card_only_statement_still_parses():
    assert len(parse_ofx(_card(make_ofx(TX, version=2))).transactions) == 2


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("which", [0, 1])
@pytest.mark.parametrize("card", [False, True])
def test_bank_error_status_raises(version, which, card):
    raw = make_ofx(TX, version=version)
    raw = _card(raw) if card else raw
    assert raw.count(b"<CODE>0") == 2  # SONRS e STMTTRNRS/CCSTMTTRNRS
    idx = -1
    for _ in range(which + 1):
        idx = raw.index(b"<CODE>0", idx + 1)
    raw = raw[:idx] + b"<CODE>15500" + raw[idx + len(b"<CODE>0") :]
    with pytest.raises(ParseError) as e:
        parse_ofx(raw)
    assert e.value.code == "invalid_format"
    assert "15500" in e.value.message and "banco" in e.value.message


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\x00\xff\xfe<OFX>",
        b"<OFX><STMTRS><STMTTRN><TRNAMT>",
        b"<OFX>" + b"<" * 5000,
        b"<OFX>" + b"<A>" * 100000,
        b"<OFX><STMTRS><STMTTRN><DTPOSTED>\x81\x8d<TRNAMT>1</STMTTRN>",
        b"\xef\xbb\xbf<OFX><STMTRS></STMTRS></OFX>",
    ],
)
def test_hostile_input_only_raises_parse_error(data):
    try:
        parse_ofx(data)
    except ParseError:
        pass


def test_thousands_like_amount_is_decimal():
    raw = make_ofx(TX).replace(b"<TRNAMT>1234.56", b"<TRNAMT>10.500", 1)
    assert parse_ofx(raw).transactions[0].amount_cents == 1050


@pytest.mark.parametrize("amount", [b"", b"1,234"])
def test_bad_trnamt(amount):
    raw = make_ofx(TX).replace(b"<TRNAMT>1234.56", b"<TRNAMT>" + amount, 1)
    with pytest.raises(ParseError) as e:
        parse_ofx(raw)
    assert e.value.code == "invalid_amount"


def test_invalid_balamt():
    raw = make_ofx(TX, ledger_balance_cents=500000).replace(b"<BALAMT>5000.00", b"<BALAMT>5x", 1)
    with pytest.raises(ParseError) as e:
        parse_ofx(raw)
    assert e.value.code == "invalid_amount"


def test_unclosed_sgml_status_still_checked_and_parsed():
    raw = make_ofx(TX, version=1).replace(b"</STATUS>", b"")
    assert len(parse_ofx(raw).transactions) == 2
    bad = raw.replace(b"<CODE>0", b"<CODE>2000", 1)
    with pytest.raises(ParseError) as e:
        parse_ofx(bad)
    assert e.value.code == "invalid_format" and "2000" in e.value.message


def test_status_without_code_accepted():
    raw = make_ofx(TX, version=2).replace(b"<CODE>0</CODE>", b"")
    assert len(parse_ofx(raw).transactions) == 2
