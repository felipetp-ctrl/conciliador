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
#  - error_message.ofx: resposta de erro do servidor, sem extrato (deve dar ParseError).
#  - multiple_accounts.ofx: dois extratos válidos, porém sem nenhum STMTTRN.
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
    assert st.transactions[0].dedup_key == ""
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


@pytest.mark.parametrize("name", ["bank_small.ofx", "error_message.ofx"])
def test_corpus_without_statement_raises(name):
    with pytest.raises(ParseError) as e:
        parse_ofx((CORPUS / name).read_bytes())
    assert e.value.code == "invalid_format"


def test_corpus_multiple_accounts_uses_first_statement():
    st = parse_ofx((CORPUS / "multiple_accounts.ofx").read_bytes())
    assert st.account.account_number == "9100"
    assert st.ledger_balance_cents == 11100
    assert st.transactions == ()


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
