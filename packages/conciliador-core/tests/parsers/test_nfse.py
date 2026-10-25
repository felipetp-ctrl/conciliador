from datetime import date

import pytest
from conciliador_core.errors import ParseError
from conciliador_core.models import Direction, Source
from conciliador_core.parsers import parse_fiscal_xml
from conciliador_synth.fiscal import make_nfse, make_nfse_cancellation

CO = "11222333000181"
THIRD = "45723174000110"
CLIENT_CNPJ = "12ABC34501DE35"
CPF = "52998224725"
K = "4" * 50
K_ALNUM = "355030811" + "12ABC34501DE35" + "1" * 27


def _nfse(**kw: object):  # type: ignore[no-untyped-def]
    base: dict[str, object] = {
        "chave": K,
        "prestador_cnpj": CO,
        "tomador_doc": CLIENT_CNPJ,
        "issued_on": date(2026, 10, 10),
        "service_cents": 200000,
        "net_cents": 190000,
        "iss_withheld_cents": 10000,
    }
    base.update(kw)
    return make_nfse(**base)  # type: ignore[arg-type]


def _code(data: bytes, company: str = CO) -> str:
    with pytest.raises(ParseError) as e:
        parse_fiscal_xml(data, company)
    return e.value.code


def test_nfse_issued_with_iss_withheld_uses_vliq():
    r = parse_fiscal_xml(_nfse(), CO)
    (it,) = r.items
    assert (it.id, it.source, it.direction, it.amount_cents, it.gross_cents, it.due_on) == (
        f"nfse:{K}:1",
        Source.NFSE,
        Direction.INFLOW,
        190000,
        200000,
        date(2026, 11, 9),
    )
    assert it.issued_on == date(2026, 10, 10)
    assert it.counterpart_doc == CLIENT_CNPJ
    assert it.document_number == "1"
    assert it.branch_cnpj == CO
    assert it.withholdings == (("vISSQN", 10000),)
    assert r.cancelled_ids == ()


def test_nfse_without_vliq_subtracts_withholding():
    (it,) = parse_fiscal_xml(_nfse(net_cents=None), CO).items
    assert (it.amount_cents, it.gross_cents) == (190000, 200000)


def test_nfse_federal_withholdings_in_fixed_order():
    data = _nfse(
        net_cents=None,
        iss_withheld_cents=10000,
        withholdings={"vRetCSLL": 2000, "vRetCP": 500, "vRetIRRF": 3000},
    )
    (it,) = parse_fiscal_xml(data, CO).items
    assert it.withholdings == (
        ("vISSQN", 10000),
        ("vRetCP", 500),
        ("vRetIRRF", 3000),
        ("vRetCSLL", 2000),
    )
    assert it.amount_cents == 200000 - 15500


def test_nfse_iss_not_retained_is_not_subtracted():
    data = _nfse(net_cents=None, iss_withheld_cents=0)
    (it,) = parse_fiscal_xml(data, CO).items
    assert (it.amount_cents, it.withholdings) == (200000, ())


def test_nfse_without_tomador():
    (it,) = parse_fiscal_xml(_nfse(tomador_doc=None), CO).items
    assert it.direction is Direction.INFLOW and it.counterpart_doc is None


def test_nfse_received_is_outflow():
    data = _nfse(prestador_cnpj=THIRD, tomador_doc=CO)
    (it,) = parse_fiscal_xml(data, CO).items
    assert it.direction is Direction.OUTFLOW and it.counterpart_doc == THIRD


def test_nfse_tomador_cpf_and_branch_prestador():
    (it,) = parse_fiscal_xml(_nfse(prestador_cnpj="11222333000262", tomador_doc=CPF), CO).items
    assert (it.direction, it.counterpart_doc) == (Direction.INFLOW, CPF)


def test_nfse_cpf_never_matches_company():
    assert _code(_nfse(prestador_cnpj=THIRD, tomador_doc=CPF)) == "not_company_document"


def test_nfse_foreign_document_rejected():
    assert _code(_nfse(prestador_cnpj=THIRD)) == "not_company_document"


def test_nfse_company_on_both_sides_yields_no_item():
    r = parse_fiscal_xml(_nfse(tomador_doc="11222333000262"), CO)
    assert r.items == ()


def test_nfse_alphanumeric_cnpj_company_and_chave():
    co = "12ABC34501DE35"
    data = _nfse(chave=K_ALNUM, prestador_cnpj=co, tomador_doc=THIRD)
    (it,) = parse_fiscal_xml(data, co).items
    assert it.id == f"nfse:{K_ALNUM}:1" and it.direction is Direction.INFLOW


def test_nfse_zero_net_yields_no_item():
    r = parse_fiscal_xml(_nfse(net_cents=0), CO)
    assert r.items == ()


def test_nfse_negative_net_is_invalid_format():
    data = _nfse(net_cents=None, service_cents=1000, iss_withheld_cents=1500)
    assert _code(data) == "invalid_format"


def test_nfse_local_date_near_midnight():
    (it,) = parse_fiscal_xml(_nfse(issued_on=date(2026, 10, 31)), CO).items
    assert it.issued_on == date(2026, 10, 31) and it.due_on == date(2026, 11, 30)


def test_nfse_cancellation():
    r = parse_fiscal_xml(make_nfse_cancellation(K), CO)
    assert r.cancelled_ids == (f"nfse:{K}",) and r.items == ()


def test_nfse_cancellation_request_without_authority_processing_ignored():
    data = make_nfse_cancellation(K, registered=False)
    assert parse_fiscal_xml(data, CO).cancelled_ids == ()


def test_nfse_other_event_ignored():
    data = make_nfse_cancellation(K).replace(b"e101101", b"e101103")
    assert parse_fiscal_xml(data, CO).cancelled_ids == ()


def test_nfse_cancellation_with_mismatched_event_id_ignored():
    data = make_nfse_cancellation(K, id_chave="5" * 50)
    assert parse_fiscal_xml(data, CO).cancelled_ids == ()


def test_nfse_cancellation_bad_chave_is_invalid_format():
    assert _code(make_nfse_cancellation("123")) == "invalid_format"


def test_unknown_root_rejected():
    assert _code(b"<a/>") == "unsupported_document"
    assert _code(b'<NFSe xmlns="http://example.com/outro"/>') == "unsupported_document"


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (b"<vServ>2000.00</vServ>", b"<vServ>abc</vServ>"),
        (b"<vServ>2000.00</vServ>", b""),
        (b"<vLiq>1900.00</vLiq>", b"<vLiq>x</vLiq>"),
        (b"<vLiq>1900.00</vLiq>", b"<vLiq>-1.00</vLiq>"),
        (b"<vISSQN>100.00</vISSQN>", b"<vISSQN>y</vISSQN>"),
        (b"<dhEmi>2026-10-10T10:00:00-03:00</dhEmi>", b"<dhEmi>ontem</dhEmi>"),
        (b"<dhEmi>2026-10-10T10:00:00-03:00</dhEmi>", b""),
        (b'Id="NFS' + K.encode() + b'"', b'Id="NFS123"'),
        (b'Id="NFS' + K.encode() + b'"', b'Id="' + K.encode() + b'"'),
        (b'Id="NFS' + K.encode() + b'"', b""),
        (b"<prest>", b"<prestx>"),
        (b"<infNFSe ", b"<infNFSex "),
    ],
)
def test_nfse_malformed_values_are_invalid_format(old, new):
    data = _nfse()
    assert old in data
    assert _code(data.replace(old, new)) == "invalid_format"


def test_nfse_dps_missing_is_invalid_format():
    data = _nfse().replace(b"<DPS", b"<DPSx").replace(b"</DPS>", b"</DPSx>")
    assert _code(data) == "invalid_format"


@pytest.mark.parametrize(
    "data",
    [
        b'<evento xmlns="http://www.sped.fazenda.gov.br/nfse"/>',
        b'<evento xmlns="http://www.sped.fazenda.gov.br/nfse"><infEvento/></evento>',
    ],
)
def test_nfse_event_without_request_is_invalid_format(data):
    assert _code(data) == "invalid_format"


def test_nfse_cancellation_without_dhproc_ignored():
    data = make_nfse_cancellation(K).replace(b"<dhProc>2026-10-12T09:00:05-03:00</dhProc>", b"")
    assert parse_fiscal_xml(data, CO).cancelled_ids == ()


def test_synth_rejects_unknown_nfse_withholding():
    with pytest.raises(ValueError, match="Retenção desconhecida"):
        _nfse(withholdings={"vFoo": 1})
