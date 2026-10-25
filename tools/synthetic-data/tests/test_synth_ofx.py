from datetime import date

from conciliador_synth.ofx import SynthTxn, make_ofx

T = [SynthTxn(date(2026, 10, 1), -15000, "PAGTO BOLETO AÇÚCAR LTDA", "A1")]


def test_v1_sgml_cp1252_has_unclosed_leaf_tags():
    raw = make_ofx(T, version=1, encoding="cp1252")
    assert raw.startswith(b"OFXHEADER:100")
    assert "AÇÚCAR".encode("cp1252") in raw
    assert b"<TRNAMT>-150.00\r\n" in raw or b"<TRNAMT>-150.00\n" in raw
    assert b"</TRNAMT>" not in raw


def test_v2_xml_utf8_and_decimal_comma():
    raw = make_ofx(T, version=2, encoding="utf-8", decimal_comma=True)
    assert raw.startswith(b"<?xml")
    assert b"<TRNAMT>-150,00</TRNAMT>" in raw


def test_dtposted_starts_with_yyyymmdd():
    raw = make_ofx(T)
    assert b"<DTPOSTED>20261001" in raw


def test_positive_and_small_amounts_no_float():
    txns = [
        SynthTxn(date(2026, 10, 2), 5, "A"),
        SynthTxn(date(2026, 10, 3), -99, "B"),
        SynthTxn(date(2026, 10, 4), 123456789, "C"),
    ]
    raw = make_ofx(txns)
    assert b"<TRNAMT>0.05" in raw
    assert b"<TRNAMT>-0.99" in raw
    assert b"<TRNAMT>1234567.89" in raw


def test_declared_charset_v1_and_v2():
    v1 = make_ofx(T, version=1, declared_charset="UTF-8")
    assert b"CHARSET:UTF-8" in v1
    v2 = make_ofx(T, version=2, encoding="utf-8", declared_charset="latin-1")
    assert b'encoding="latin-1"' in v2


def test_ledger_balance_and_range():
    raw = make_ofx(T, ledger_balance_cents=-1050, start=date(2026, 10, 1), end=date(2026, 10, 31))
    assert b"<LEDGERBAL>" in raw
    assert b"<BALAMT>-10.50" in raw
    assert b"<DTSTART>20261001" in raw
    assert b"<DTEND>20261031" in raw


def test_omit_optional():
    raw = make_ofx(
        T,
        omit_optional=True,
        ledger_balance_cents=100,
        start=date(2026, 10, 1),
        end=date(2026, 10, 2),
    )
    for tag in (b"DTSTART", b"DTEND", b"LEDGERBAL", b"FITID"):
        assert tag not in raw


def test_account_fields_and_structure():
    raw = make_ofx(T, bank_id="0001", branch="9", account="1-2")
    for s in (b"<BANKID>0001", b"<BRANCHID>9", b"<ACCTID>1-2", b"<BANKTRANLIST>", b"<STMTTRN>"):
        assert s in raw


def test_v2_is_well_formed_xml():
    from defusedxml.ElementTree import fromstring

    raw = make_ofx(T, version=2, encoding="utf-8", ledger_balance_cents=0)
    assert fromstring(raw).tag == "OFX"


def test_v2_escapes_memo():
    raw = make_ofx([SynthTxn(date(2026, 10, 1), -1, "A & B <C>")], version=2, encoding="utf-8")
    assert b"A &amp; B &lt;C&gt;" in raw
