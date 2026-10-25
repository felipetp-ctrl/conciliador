"""Arquivos hostis: só ParseError pode escapar dos parsers; resultados bem tipados."""

import random
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from conciliador_core import (
    BankTransaction,
    CsvParseResult,
    ExpectedItem,
    FiscalParseResult,
    ParseError,
    Statement,
    parse_fiscal_xml,
    parse_items_csv,
    parse_ofx,
    template_csv,
)
from conciliador_core.money import parse_brl_amount
from conciliador_synth.fiscal import make_nfe, make_nfe_cancellation, make_nfse
from conciliador_synth.ofx import SynthTxn, make_ofx
from hypothesis import given, settings
from hypothesis import strategies as st

COMPANY = "11222333000181"
OTHER = "52998224725"
CORPUS = Path(__file__).parent / "corpus"

PARSERS: list[Callable[[bytes], Any]] = [
    parse_ofx,
    lambda b: parse_fiscal_xml(b, COMPANY),
    parse_items_csv,
]


def _check_item(item: ExpectedItem) -> None:
    assert type(item.amount_cents) is int
    assert type(item.due_on) is date
    assert item.issued_on is None or type(item.issued_on) is date


def _check_result(result: object) -> None:
    if isinstance(result, Statement):
        for t in result.transactions:
            assert isinstance(t, BankTransaction)
            assert type(t.amount_cents) is int
            assert type(t.posted_on) is date
            assert all(ord(c) >= 32 and ord(c) != 127 for c in t.memo)
    elif isinstance(result, (CsvParseResult, FiscalParseResult)):
        for item in result.items:
            _check_item(item)


def _run(parser: Callable[[bytes], Any], data: bytes) -> None:
    try:
        result = parser(data)
    except ParseError:
        return
    _check_result(result)


@settings(max_examples=300, deadline=1000)
@given(st.binary(max_size=4096))
def test_random_bytes_only_raise_parse_error(data):
    for p in PARSERS:
        _run(p, data)


@settings(max_examples=300, deadline=1000)
@given(st.text(max_size=40))
def test_parse_brl_amount_never_crashes(s):
    try:
        value = parse_brl_amount(s)
    except ParseError:
        return
    assert type(value) is int


def _synthetic_samples() -> dict[str, tuple[bytes, Callable[[bytes], Any]]]:
    txns = [
        SynthTxn(date(2026, 10, 1), 123456, "PIX RECEBIDO 52998224725 JOSÉ", "F1"),
        SynthTxn(date(2026, 10, 2), -9990, "TARIFA PACOTE", "F2"),
    ]
    fiscal: Callable[[bytes], Any] = lambda b: parse_fiscal_xml(b, COMPANY)  # noqa: E731
    chave = "1" * 44
    return {
        "ofx1": (make_ofx(txns, version=1, ledger_balance_cents=500000), parse_ofx),
        "ofx2": (make_ofx(txns, version=2, encoding="utf-8", decimal_comma=True), parse_ofx),
        "nfe": (
            make_nfe(
                chave=chave,
                emit_cnpj=COMPANY,
                dest_doc=OTHER,
                issued_on=date(2026, 10, 1),
                total_cents=100000,
                duplicatas=[("001", date(2026, 11, 1), 50000), ("002", date(2026, 12, 1), 50000)],
                withholdings={"vRetPIS": 650},
            ),
            fiscal,
        ),
        "nfe_cancel": (make_nfe_cancellation(chave), fiscal),
        "nfse": (
            make_nfse(
                chave="2" * 50,
                prestador_cnpj=COMPANY,
                tomador_doc=OTHER,
                issued_on=date(2026, 10, 1),
                service_cents=100000,
                net_cents=90000,
                iss_withheld_cents=5000,
                withholdings={"vRetCP": 1000},
            ),
            fiscal,
        ),
        "csv": (template_csv(), parse_items_csv),
        "csv_rows": (
            b"tipo;valor;vencimento;contraparte_nome\nreceber;1.500,00;05/11/2026;Jo\xe3o\n"
            b"pagar;10,50;01/12/2026;x\n",
            parse_items_csv,
        ),
    }


SAMPLES = _synthetic_samples()


def _mutate(data: bytes, rng: random.Random) -> bytes:
    buf = bytearray(data)
    for _ in range(rng.randint(1, 8)):
        op = rng.choice(["flip", "truncate", "insert", "delete"])
        if not buf:
            buf.append(rng.randrange(256))
            continue
        pos = rng.randrange(len(buf))
        if op == "flip":
            buf[pos] ^= 1 << rng.randrange(8)
        elif op == "truncate":
            del buf[pos:]
        elif op == "insert":
            buf[pos:pos] = bytes(rng.randrange(256) for _ in range(rng.randint(1, 6)))
        else:
            del buf[pos : pos + rng.randint(1, 10)]
    return bytes(buf)


@pytest.mark.parametrize("name", sorted(SAMPLES))
@settings(max_examples=150, deadline=1000)
@given(seed=st.integers(0, 2**32 - 1))
def test_mutated_valid_files_only_raise_parse_error(name, seed):
    data, parser = SAMPLES[name]
    _run(parser, _mutate(data, random.Random(seed)))  # noqa: S311 - fuzz determinístico, não é criptografia


def test_synthetic_samples_are_valid():
    for name, (data, parser) in SAMPLES.items():
        if name != "nfe_cancel":
            parser(data)


def _truncation_inputs() -> list[tuple[str, bytes, Callable[[bytes], Any]]]:
    out = [(n, d, p) for n, (d, p) in SAMPLES.items()]
    for path in sorted((CORPUS / "ofx").glob("*.ofx")):
        out.append((path.name, path.read_bytes(), parse_ofx))
    return out


@pytest.mark.parametrize(
    ("name", "data", "parser"), _truncation_inputs(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_truncated_valid_files_raise_parse_error(name, data, parser):
    _run(parser, data[: len(data) // 2])


def test_control_chars_in_memo_are_stripped():
    raw = make_ofx([SynthTxn(date(2026, 10, 1), 100, "PAGTO\x00\x1bTESTE\x07\x7f FIM", "F1")])
    st_ = parse_ofx(raw)
    memo = st_.transactions[0].memo
    assert all(ord(c) >= 32 and ord(c) != 127 for c in memo)
    assert "PAGTO" in memo
    assert "FIM" in memo


def test_control_chars_in_csv_text_fields_are_stripped():
    raw = (
        b"tipo;valor;vencimento;contraparte_nome;descricao\n"
        b"receber;1,00;01/01/2027;Jo\x00\x1bao\x07;a\x00b\n"
    )
    r = parse_items_csv(raw)
    assert len(r.items) == 1
    assert r.items[0].counterpart_name == "Joao"
