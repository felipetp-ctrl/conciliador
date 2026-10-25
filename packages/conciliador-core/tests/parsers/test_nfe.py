from datetime import date

import pytest
from conciliador_core.errors import ParseError
from conciliador_core.models import Direction, Source
from conciliador_core.parsers import (
    MAX_FILE_BYTES,
    MAX_XML_BYTES,
    parse_fiscal_xml,
    safe_parse_xml,
)
from conciliador_synth.fiscal import NFE_NS, make_nfe, make_nfe_cancellation

CO = "11222333000181"
CLIENT = "52998224725"
K = "3" * 44
BRANCH = "11222333000262"


def _nfe(**kw: object):  # type: ignore[no-untyped-def]
    base: dict[str, object] = {
        "chave": K,
        "emit_cnpj": CO,
        "dest_doc": CLIENT,
        "issued_on": date(2026, 10, 1),
        "total_cents": 100000,
    }
    base.update(kw)
    return make_nfe(**base)  # type: ignore[arg-type]


def _code(data: bytes, company: str = CO) -> str:
    with pytest.raises(ParseError) as e:
        parse_fiscal_xml(data, company)
    return e.value.code


def test_issued_without_dup_uses_net_and_default_due():
    r = parse_fiscal_xml(_nfe(withholdings={"vRetPIS": 650, "vIRRF": 1500}), CO)
    (it,) = r.items
    assert (it.id, it.direction, it.amount_cents, it.gross_cents) == (
        f"nfe:{K}:1",
        Direction.INFLOW,
        97850,
        100000,
    )
    assert it.due_on == date(2026, 10, 31) and it.counterpart_doc == CLIENT
    assert it.source is Source.NFE and it.issued_on == date(2026, 10, 1)
    assert it.withholdings == (("vRetPIS", 650), ("vIRRF", 1500))
    assert it.counterpart_name == "DESTINATARIO SINTETICO"
    assert it.document_number == "123" and it.branch_cnpj == CO


def test_withholdings_fixed_order_and_zero_omitted():
    r = parse_fiscal_xml(
        _nfe(withholdings={"vRetPrev": 10, "vRetCSLL": 20, "vRetCOFINS": 0, "vRetPIS": 5}), CO
    )
    assert r.items[0].withholdings == (("vRetPIS", 5), ("vRetCSLL", 20), ("vRetPrev", 10))


def test_default_due_days_configurable():
    r = parse_fiscal_xml(_nfe(), CO, default_due_days=10)
    assert r.items[0].due_on == date(2026, 10, 11)


def test_duplicatas_become_items():
    r = parse_fiscal_xml(
        _nfe(
            emit_cnpj="12ABC34501DE35",
            dest_doc=CO,
            total_cents=30000,
            withholdings={"vIRRF": 300},
            duplicatas=[("001", date(2026, 11, 1), 15000), ("002", date(2026, 12, 1), 15000)],
        ),
        CO,
    )
    assert [(i.id, i.direction, i.due_on) for i in r.items] == [
        (f"nfe:{K}:001", Direction.OUTFLOW, date(2026, 11, 1)),
        (f"nfe:{K}:002", Direction.OUTFLOW, date(2026, 12, 1)),
    ]
    assert [i.amount_cents for i in r.items] == [15000, 15000]
    assert all(i.gross_cents == 30000 and i.withholdings == (("vIRRF", 300),) for i in r.items)
    assert r.items[0].counterpart_doc == "12ABC34501DE35"


def test_repeated_ndup_gets_unique_ids():
    r = parse_fiscal_xml(
        _nfe(duplicatas=[("1", date(2026, 11, 1), 500), ("1", date(2026, 12, 1), 500)]), CO
    )
    assert len({i.id for i in r.items}) == 2


def test_branch_matches_by_root():
    r = parse_fiscal_xml(_nfe(emit_cnpj=BRANCH, total_cents=100), CO)
    assert r.items[0].branch_cnpj == BRANCH


def test_formatted_company_cnpj_accepted():
    assert len(parse_fiscal_xml(_nfe(), "11.222.333/0001-81").items) == 1


def test_invalid_company_cnpj_is_value_error():
    with pytest.raises(ValueError):
        parse_fiscal_xml(_nfe(), "11222333000180")


def test_transfer_between_branches_yields_no_item():
    r = parse_fiscal_xml(_nfe(dest_doc=BRANCH, total_cents=100), CO)
    assert r.items == () and r.cancelled_ids == ()


def test_foreign_document_rejected():
    assert _code(_nfe(emit_cnpj="27373722000148")) == "not_company_document"


def test_cpf_never_matches_company():
    assert _code(_nfe(emit_cnpj="27373722000148", dest_doc="11222333000")) == "not_company_document"


def test_cancellation_event():
    r = parse_fiscal_xml(make_nfe_cancellation(K), CO)
    assert r.cancelled_ids == (f"nfe:{K}",) and r.items == ()


def test_other_event_ignored():
    data = make_nfe_cancellation(K).replace(b"110111", b"110110")
    assert parse_fiscal_xml(data, CO).cancelled_ids == ()


def test_rejected_cancellation_ignored():
    data = make_nfe_cancellation(K).replace(b"<cStat>135", b"<cStat>573")
    assert parse_fiscal_xml(data, CO).cancelled_ids == ()


def test_cancellation_request_without_ret_evento_ignored():
    r = parse_fiscal_xml(make_nfe_cancellation(K, status=None), CO)
    assert r.cancelled_ids == () and r.items == ()


def test_cancellation_with_mismatched_ret_chave_ignored():
    r = parse_fiscal_xml(make_nfe_cancellation(K, ret_chave="4" * 44), CO)
    assert r.cancelled_ids == () and r.items == ()


def test_cancellation_late_status_155_accepted():
    assert parse_fiscal_xml(make_nfe_cancellation(K, status="155"), CO).cancelled_ids == (
        f"nfe:{K}",
    )


def test_zero_net_yields_no_item():
    r = parse_fiscal_xml(_nfe(total_cents=1000, withholdings={"vIRRF": 1000}), CO)
    assert r.items == () and r.cancelled_ids == ()
    assert parse_fiscal_xml(_nfe(total_cents=0), CO).items == ()


def test_local_date_near_midnight_is_kept():
    data = _nfe().replace(b"T10:00:00-03:00", b"T23:30:00-03:00")
    (it,) = parse_fiscal_xml(data, CO).items
    assert it.issued_on == date(2026, 10, 1) and it.due_on == date(2026, 10, 31)


def test_bare_nfe_root_supported():
    data = _nfe().replace(b"<nfeProc", b"<x").replace(b"</nfeProc>", b"</x>")
    inner = data[data.index(b"<NFe>") : data.index(b"</NFe>") + 6]
    bare = inner.replace(b"<NFe>", f'<NFe xmlns="{NFE_NS}">'.encode(), 1)
    assert parse_fiscal_xml(bare, CO).items[0].id == f"nfe:{K}:1"


@pytest.mark.parametrize(
    "payload",
    [
        b'<?xml version="1.0"?><!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>',
        b'<?xml version="1.0"?><!DOCTYPE a [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><a>&b;</a>',
        b'<?xml version="1.0"?><!DOCTYPE a><a/>',
    ],
)
def test_xxe_and_billion_laughs_rejected(payload):
    assert _code(payload) == "xml_forbidden"


def test_too_large():
    assert _code(b"<a>" + b" " * MAX_FILE_BYTES + b"</a>") == "too_large"


def test_xml_cap_is_2_mib():
    assert MAX_XML_BYTES == 2 * 1024 * 1024
    assert _code(b"<a>" + b" " * MAX_XML_BYTES + b"</a>") == "too_large"
    assert safe_parse_xml(b"<a>" + b" " * (MAX_XML_BYTES - 10) + b"</a>").tag == "a"


def test_safe_parse_xml_returns_element():
    assert safe_parse_xml(b"<a><b/></a>").tag == "a"


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not xml",
        b"<a>",
        b"\xff\xfe\x00",
        b'<?xml version="1.0" encoding="foo"?><a/>',
    ],
)
def test_garbage_is_invalid_format(data):
    assert _code(data) == "invalid_format"


def test_unknown_root_is_unsupported_document():
    assert _code(b"<a/>") == "unsupported_document"


def _mutate(old: bytes, new: bytes) -> bytes:
    data = _nfe(withholdings={"vRetPIS": 650}, duplicatas=[("1", date(2026, 11, 1), 500)])
    assert old in data
    return data.replace(old, new)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (b"<vNF>1000.00</vNF>", b"<vNF>abc</vNF>"),
        (b"<vNF>1000.00</vNF>", b"<vNF>-5.00</vNF>"),
        (b"<vNF>1000.00</vNF>", b""),
        (b"<vDup>5.00</vDup>", b"<vDup>0.00</vDup>"),
        (b"<vDup>5.00</vDup>", b"<vDup>x</vDup>"),
        (b"<dVenc>2026-11-01</dVenc>", b"<dVenc>2026-02-30</dVenc>"),
        (b"<dVenc>2026-11-01</dVenc>", b"<dVenc>01/11/2026</dVenc>"),
        (b"<dhEmi>2026-10-01T10:00:00-03:00</dhEmi>", b"<dhEmi>ontem</dhEmi>"),
        (b"<dhEmi>2026-10-01T10:00:00-03:00</dhEmi>", b""),
        (b'Id="NFe' + K.encode() + b'"', b'Id="NFe123"'),
        (b'Id="NFe' + K.encode() + b'"', b""),
        (b"<vRetPIS>6.50</vRetPIS>", b"<vRetPIS>z</vRetPIS>"),
        (b"<emit>", b"<emitx>"),
    ],
)
def test_malformed_values_are_invalid_format(old, new):
    assert _code(_mutate(old, new)) == "invalid_format"


def test_non_positive_net_is_invalid_format():
    assert _code(_nfe(total_cents=1000, withholdings={"vIRRF": 1500})) == "invalid_format"


def test_amount_with_three_decimals_not_misread():
    data = _nfe(total_cents=100000).replace(b"1000.00", b"10.500")
    assert parse_fiscal_xml(data, CO).items[0].amount_cents == 1050


def test_synth_rejects_unknown_withholding():
    with pytest.raises(ValueError):
        _nfe(withholdings={"vFoo": 1})
