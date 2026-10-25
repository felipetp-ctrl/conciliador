from datetime import date

import pytest
from conciliador_core.errors import ParseError
from conciliador_core.models import Direction, Source
from conciliador_core.parsers import MAX_FILE_BYTES
from conciliador_core.parsers.csv_items import parse_items_csv, template_csv

CNPJ = "11.222.333/0001-81"
CPF = "529.982.247-25"


def test_semicolon_cp1252_variants():
    raw = (
        "tipo;valor;vencimento;contraparte_nome\nreceber;1.500,00;05/11/2026;João\npagar;-;x;\n"
    ).encode("cp1252")
    r = parse_items_csv(raw)
    assert [(i.direction, i.amount_cents, i.due_on, i.counterpart_name) for i in r.items] == [
        (Direction.INFLOW, 150000, date(2026, 11, 5), "João")
    ]
    assert r.items[0].source == Source.CSV
    assert r.errors[0].line == 3


def test_comma_delimiter_utf8_bom():
    raw = "﻿Tipo,Valor,Vencimento,Descrição\nPagar,R$ 10.50,01/12/2026,x\n".encode()
    r = parse_items_csv(raw)
    assert r.errors == ()
    assert r.items[0].direction == Direction.OUTFLOW
    assert r.items[0].amount_cents == 1050


def test_semicolon_wins_tie_and_extra_columns_ignored():
    r = parse_items_csv(b"tipo;valor;vencimento;extra\nreceber;1,00;01/01/2027;z\n")
    assert len(r.items) == 1
    assert r.errors == ()


def test_ids_are_deterministic_and_prefixed():
    raw = f"tipo;valor;vencimento;contraparte_documento\nreceber;1,00;01/01/2027;{CNPJ}\n".encode()
    a, b = parse_items_csv(raw), parse_items_csv(raw)
    assert a.items[0].id == b.items[0].id
    assert a.items[0].id.startswith("csv:")
    assert len(a.items[0].id) == 4 + 16
    assert a.items[0].counterpart_doc == "11222333000181"


def test_id_differs_by_fields():
    raw = b"tipo;valor;vencimento\nreceber;1,00;01/01/2027\nreceber;1,01;01/01/2027\n"
    r = parse_items_csv(raw)
    assert r.items[0].id != r.items[1].id


def test_duplicate_row_reported_keep_first():
    raw = b"tipo;valor;vencimento\nreceber;1,00;01/01/2027\n\nreceber;1,00;01/01/2027\n"
    r = parse_items_csv(raw)
    assert len(r.items) == 1
    assert [(e.line, e.message) for e in r.errors] == [(4, "linha duplicada")]


def test_invalid_document_is_row_error():
    raw = b"tipo;valor;vencimento;contraparte_documento\nreceber;1,00;01/01/2027;123\n"
    r = parse_items_csv(raw)
    assert r.items == ()
    assert r.errors[0].message == "documento inválido"


def test_valid_cpf_is_normalized():
    raw = f"tipo;valor;vencimento;contraparte_documento\npagar;1,00;01/01/2027;{CPF}\n".encode()
    assert parse_items_csv(raw).items[0].counterpart_doc == "52998224725"


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ("receber;abc;01/01/2027", "valor inválido"),
        ("receber;-5,00;01/01/2027", "valor deve ser positivo"),
        ("receber;0,00;01/01/2027", "valor deve ser positivo"),
        ("receber;1,00;2027-01-01", "vencimento inválido: use DD/MM/AAAA"),
        ("receber;1,00;31/02/2027", "vencimento inválido: use DD/MM/AAAA"),
        ("outro;1,00;01/01/2027", "tipo deve ser receber ou pagar"),
        (";1,00;01/01/2027", "tipo deve ser receber ou pagar"),
    ],
)
def test_row_errors(row, message):
    r = parse_items_csv(f"tipo;valor;vencimento\n{row}\n".encode())
    assert r.items == ()
    assert [(e.line, e.message) for e in r.errors] == [(2, message)]


@pytest.mark.parametrize(
    "raw",
    [b"tipo;valor\nreceber;1,00\n", b"tipo;valor;vencimento;valor\nreceber;1;2;3\n", b"a;b;c\n"],
)
def test_bad_header(raw):
    with pytest.raises(ParseError) as exc:
        parse_items_csv(raw)
    assert exc.value.code == "invalid_format"


def test_header_names_normalized_and_values_trimmed():
    raw = b"  TIPO ;Valor;VENCIMENTO;Contraparte_Nome\n receber ; 2,00 ;01/01/2027;  Ana  \n"
    r = parse_items_csv(raw)
    assert r.items[0].counterpart_name == "Ana"


@pytest.mark.parametrize("raw", [b"", b"\xef\xbb\xbf", b"tipo;valor;vencimento\n"])
def test_empty_or_header_only(raw):
    r = parse_items_csv(raw)
    assert r.items == ()
    assert r.errors == ()


def test_too_large_bytes():
    with pytest.raises(ParseError) as exc:
        parse_items_csv(b"x" * (MAX_FILE_BYTES + 1))
    assert exc.value.code == "too_large"


def test_too_many_rows():
    rows = "".join(f"receber;{i + 1},00;01/01/2027\n" for i in range(10_001))
    with pytest.raises(ParseError) as exc:
        parse_items_csv(("tipo;valor;vencimento\n" + rows).encode())
    assert exc.value.code == "too_large"


def test_exactly_max_rows_ok():
    rows = "".join(f"receber;{i + 1},00;01/01/2027\n" for i in range(10_000))
    r = parse_items_csv(("tipo;valor;vencimento\n" + rows).encode())
    assert len(r.items) == 10_000


def test_template_parses_cleanly():
    raw = template_csv()
    assert raw.startswith(b"\xef\xbb\xbf")
    r = parse_items_csv(raw)
    assert r.errors == ()
    assert {i.direction for i in r.items} == {Direction.INFLOW, Direction.OUTFLOW}
    assert len(r.items) == 2
