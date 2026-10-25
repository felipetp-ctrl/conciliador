"""Gerador de XMLs fiscais sintéticos (NF-e e NFS-e, com eventos de cancelamento) para testes.

Os documentos seguem os nomes e caminhos do leiaute 4.00 da NF-e e do leiaute 1.01 da NFS-e
nacional, mas contêm apenas o subconjunto lido pelo parser (não são válidos contra o XSD
completo).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from html import escape

NFE_NS = "http://www.portalfiscal.inf.br/nfe"
NFSE_NS = "http://www.sped.fazenda.gov.br/nfse"
NFSE_WITHHOLDING_NAMES = ("vRetCP", "vRetIRRF", "vRetCSLL")
WITHHOLDING_NAMES = ("vRetPIS", "vRetCOFINS", "vRetCSLL", "vIRRF", "vRetPrev")


def _money(cents: int) -> str:
    whole, frac = divmod(cents, 100)
    return f"{whole}.{frac:02d}"


def _party_doc(doc: str) -> str:
    tag = "CPF" if len(doc) == 11 else "CNPJ"
    return f"<{tag}>{escape(doc)}</{tag}>"


def make_nfe(
    *,
    chave: str,
    emit_cnpj: str,
    dest_doc: str,
    issued_on: date,
    total_cents: int,
    duplicatas: Sequence[tuple[str, date, int]] = (),
    withholdings: Mapping[str, int] = {},  # noqa: B006 - nunca é alterado
    number: str = "123",
    tp_nf: str | None = "1",
    mod: str | None = "55",
    tp_amb: str | None = "1",
    t_pag: Sequence[str] = (),
    prot_status: str | None = "100",
) -> bytes:
    """NF-e sintética (``nfeProc``). Valores em centavos; ``dest_doc`` com 11 caracteres é CPF.

    ``tp_nf`` (``ide/tpNF``: 1 saída, 0 entrada), ``mod`` (``ide/mod``) e ``tp_amb``
    (``ide/tpAmb``: 1 produção, 2 homologação) são omitidos com ``None``. ``t_pag`` gera um
    ``pag/detPag`` por meio de pagamento (``tPag``; "90" = sem pagamento); vazio omite ``pag``.
    ``prot_status`` é o ``protNFe/infProt/cStat`` (``None`` omite o ``protNFe``).
    """
    unknown = set(withholdings) - set(WITHHOLDING_NAMES)
    if unknown:
        raise ValueError(f"Retenção desconhecida: {sorted(unknown)}")
    ret = "".join(
        f"<{name}>{_money(withholdings[name])}</{name}>"
        for name in WITHHOLDING_NAMES
        if name in withholdings
    )
    ret_xml = f"<retTrib>{ret}</retTrib>" if ret else ""
    dups = "".join(
        f"<dup><nDup>{escape(n)}</nDup><dVenc>{d.isoformat()}</dVenc><vDup>{_money(v)}</vDup></dup>"
        for n, d, v in duplicatas
    )
    cobr = f"<cobr>{dups}</cobr>" if dups else ""
    det_pag = "".join(
        f"<detPag><tPag>{escape(t)}</tPag><vPag>{_money(total_cents)}</vPag></detPag>"
        for t in t_pag
    )
    pag = f"<pag>{det_pag}</pag>" if det_pag else ""

    def leaf(tag: str, value: str | None) -> str:
        return f"<{tag}>{escape(value)}</{tag}>" if value is not None else ""

    prot = (
        f'<protNFe versao="4.00"><infProt><tpAmb>1</tpAmb><chNFe>{chave}</chNFe>'
        f"{leaf('cStat', prot_status)}</infProt></protNFe>"
        if prot_status is not None
        else ""
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<nfeProc xmlns="{NFE_NS}" versao="4.00"><NFe><infNFe versao="4.00" Id="NFe{chave}">'
        f"<ide>{leaf('mod', mod)}<nNF>{escape(number)}</nNF>"
        f"<dhEmi>{issued_on.isoformat()}T10:00:00-03:00</dhEmi>"
        f"{leaf('tpNF', tp_nf)}{leaf('tpAmb', tp_amb)}</ide>"
        f"<emit>{_party_doc(emit_cnpj)}<xNome>EMITENTE SINTETICO LTDA</xNome></emit>"
        f"<dest>{_party_doc(dest_doc)}<xNome>DESTINATARIO SINTETICO</xNome></dest>"
        f"<total><ICMSTot><vNF>{_money(total_cents)}</vNF></ICMSTot>{ret_xml}</total>"
        f"{cobr}{pag}</infNFe></NFe>{prot}</nfeProc>"
    )
    return xml.encode("utf-8")


def make_nfe_cancellation(
    chave: str, *, status: str | None = "135", ret_chave: str | None = None
) -> bytes:
    """``procEventoNFe`` de cancelamento (``tpEvento`` 110111).

    Por padrão traz o ``retEvento`` homologado (``cStat`` 135). ``status=None`` omite o
    ``retEvento`` (mero pedido); ``ret_chave`` altera a chave do ``retEvento``.
    """
    ret = ""
    if status is not None:
        ret = (
            f'<retEvento versao="1.00"><infEvento><cStat>{escape(status)}</cStat>'
            f"<chNFe>{ret_chave or chave}</chNFe><tpEvento>110111</tpEvento>"
            "</infEvento></retEvento>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<procEventoNFe xmlns="{NFE_NS}" versao="1.00">'
        f'<evento versao="1.00"><infEvento Id="ID110111{chave}01">'
        f"<chNFe>{chave}</chNFe><tpEvento>110111</tpEvento><nSeqEvento>1</nSeqEvento>"
        '<detEvento versao="1.00"><descEvento>Cancelamento</descEvento></detEvento>'
        f"</infEvento></evento>{ret}</procEventoNFe>"
    )
    return xml.encode("utf-8")


def make_nfse(
    *,
    chave: str,
    prestador_cnpj: str,
    tomador_doc: str | None,
    issued_on: date,
    service_cents: int,
    net_cents: int | None,
    iss_withheld_cents: int = 0,
    number: str = "1",
    iss_amount_cents: int = 0,
    withholdings: Mapping[str, int] | None = None,
    substitutes: str | None = None,
) -> bytes:
    """NFS-e nacional sintética (``NFSe``). Valores em centavos.

    ``substitutes`` é a chave (50 caracteres) da NFS-e substituída (``infDPS/subst/chSubstda``).

    ``chave`` são os 50 caracteres após ``NFS`` no ``infNFSe/@Id``. ``net_cents=None`` omite
    ``valores/vLiq``. ``iss_withheld_cents > 0`` marca o ISSQN como retido pelo tomador
    (``tpRetISSQN`` 2) e informa ``valores/vISSQN``; ``iss_amount_cents`` informa o ISSQN devido
    sem retenção (``tpRetISSQN`` 1). ``withholdings`` aceita ``vRetCP``,
    ``vRetIRRF`` e ``vRetCSLL``. ``tomador_doc`` com 11 caracteres é CPF; ``None`` omite ``toma``.
    """
    withholdings = withholdings or {}
    unknown = set(withholdings) - set(NFSE_WITHHOLDING_NAMES)
    if unknown:
        raise ValueError(f"Retenção desconhecida: {sorted(unknown)}")
    fed = "".join(
        f"<{name}>{_money(withholdings[name])}</{name}>"
        for name in NFSE_WITHHOLDING_NAMES
        if name in withholdings
    )
    trib_fed = f"<tribFed>{fed}</tribFed>" if fed else ""
    retained = iss_withheld_cents > 0
    iss_value = iss_withheld_cents if retained else iss_amount_cents
    iss = f"<vISSQN>{_money(iss_value)}</vISSQN>" if iss_value > 0 else ""
    liq = f"<vLiq>{_money(net_cents)}</vLiq>" if net_cents is not None else ""
    toma = (
        f"<toma>{_party_doc(tomador_doc)}<xNome>TOMADOR SINTETICO</xNome></toma>"
        if tomador_doc is not None
        else ""
    )
    subst = (
        f"<subst><chSubstda>{escape(substitutes)}</chSubstda><cMotivo>99</cMotivo>"
        "<xMotivo>Substituicao sintetica</xMotivo></subst>"
        if substitutes is not None
        else ""
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<NFSe xmlns="{NFSE_NS}" versao="1.01"><infNFSe Id="NFS{chave}">'
        f"<nNFSe>{escape(number)}</nNFSe><cStat>100</cStat>"
        f"<emit>{_party_doc(prestador_cnpj)}<xNome>PRESTADOR SINTETICO LTDA</xNome></emit>"
        f"<valores>{iss}{liq}</valores>"
        '<DPS versao="1.01"><infDPS>'
        f"<dhEmi>{issued_on.isoformat()}T10:00:00-03:00</dhEmi>{subst}"
        f"<prest>{_party_doc(prestador_cnpj)}</prest>{toma}"
        f"<valores><vServPrest><vServ>{_money(service_cents)}</vServ></vServPrest>"
        f"<trib><tribMun><tribISSQN>1</tribISSQN><tpRetISSQN>{2 if retained else 1}</tpRetISSQN>"
        f"</tribMun>{trib_fed}</trib></valores>"
        "</infDPS></DPS></infNFSe></NFSe>"
    )
    return xml.encode("utf-8")


def make_nfse_cancellation(
    chave: str,
    *,
    registered: bool = True,
    id_chave: str | None = None,
    substituta: str | None = None,
) -> bytes:
    """Evento de cancelamento de NFS-e (``e101101``).

    Por padrão é o ``evento`` já processado pela autoridade (traz ``dhProc``/``nDFSe``).
    ``registered=False`` gera só o ``pedRegEvento`` (mero pedido); ``id_chave`` altera a
    chave embutida no ``Id`` do ``infEvento``. ``substituta`` (chave da NFS-e nova) gera o
    cancelamento por substituição (``e105102`` com ``chSubstituta``).
    """
    if substituta is None:
        code = "101101"
        detail = (
            "<e101101><xDesc>Cancelamento de NFS-e</xDesc>"
            "<cMotivo>1</cMotivo><xMotivo>Erro na emissao</xMotivo></e101101>"
        )
    else:
        code = "105102"
        detail = (
            "<e105102><xDesc>Cancelamento de NFS-e por Substituicao</xDesc>"
            f"<cMotivo>99</cMotivo><chSubstituta>{escape(substituta)}</chSubstituta></e105102>"
        )
    ped = (
        '<pedRegEvento versao="1.01">'
        f'<infPedReg Id="PRE{chave}{code}"><tpAmb>1</tpAmb><verAplic>SINTETICO</verAplic>'
        "<dhEvento>2026-10-12T09:00:00-03:00</dhEvento><CNPJAutor>11222333000181</CNPJAutor>"
        f"<chNFSe>{chave}</chNFSe>{detail}"
        "</infPedReg></pedRegEvento>"
    )
    if not registered:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            + ped.replace("<pedRegEvento ", f'<pedRegEvento xmlns="{NFSE_NS}" ', 1)
        ).encode("utf-8")
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<evento xmlns="{NFSE_NS}" versao="1.01">'
        f'<infEvento Id="EVT{id_chave or chave}{code}001"><verAplic>SINTETICO</verAplic>'
        "<ambGer>1</ambGer><nSeqEvento>1</nSeqEvento><dhProc>2026-10-12T09:00:05-03:00</dhProc>"
        f"<nDFSe>1</nDFSe>{ped}</infEvento></evento>"
    )
    return xml.encode("utf-8")
