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
) -> bytes:
    """NF-e sintética (``nfeProc``). Valores em centavos; ``dest_doc`` com 11 caracteres é CPF."""
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
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<nfeProc xmlns="{NFE_NS}" versao="4.00"><NFe><infNFe versao="4.00" Id="NFe{chave}">'
        f"<ide><mod>55</mod><nNF>{escape(number)}</nNF>"
        f"<dhEmi>{issued_on.isoformat()}T10:00:00-03:00</dhEmi></ide>"
        f"<emit>{_party_doc(emit_cnpj)}<xNome>EMITENTE SINTETICO LTDA</xNome></emit>"
        f"<dest>{_party_doc(dest_doc)}<xNome>DESTINATARIO SINTETICO</xNome></dest>"
        f"<total><ICMSTot><vNF>{_money(total_cents)}</vNF></ICMSTot>{ret_xml}</total>"
        f"{cobr}</infNFe></NFe></nfeProc>"
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
    withholdings: Mapping[str, int] = {},  # noqa: B006 - nunca é alterado
) -> bytes:
    """NFS-e nacional sintética (``NFSe``). Valores em centavos.

    ``chave`` são os 50 caracteres após ``NFS`` no ``infNFSe/@Id``. ``net_cents=None`` omite
    ``valores/vLiq``. ``iss_withheld_cents > 0`` marca o ISSQN como retido pelo tomador
    (``tpRetISSQN`` 2) e informa ``valores/vISSQN``. ``withholdings`` aceita ``vRetCP``,
    ``vRetIRRF`` e ``vRetCSLL``. ``tomador_doc`` com 11 caracteres é CPF; ``None`` omite ``toma``.
    """
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
    iss = f"<vISSQN>{_money(iss_withheld_cents)}</vISSQN>" if retained else ""
    liq = f"<vLiq>{_money(net_cents)}</vLiq>" if net_cents is not None else ""
    toma = (
        f"<toma>{_party_doc(tomador_doc)}<xNome>TOMADOR SINTETICO</xNome></toma>"
        if tomador_doc is not None
        else ""
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<NFSe xmlns="{NFSE_NS}" versao="1.01"><infNFSe Id="NFS{chave}">'
        f"<nNFSe>{escape(number)}</nNFSe><cStat>100</cStat>"
        f"<emit>{_party_doc(prestador_cnpj)}<xNome>PRESTADOR SINTETICO LTDA</xNome></emit>"
        f"<valores>{iss}{liq}</valores>"
        '<DPS versao="1.01"><infDPS>'
        f"<dhEmi>{issued_on.isoformat()}T10:00:00-03:00</dhEmi>"
        f"<prest>{_party_doc(prestador_cnpj)}</prest>{toma}"
        f"<valores><vServPrest><vServ>{_money(service_cents)}</vServ></vServPrest>"
        f"<trib><tribMun><tribISSQN>1</tribISSQN><tpRetISSQN>{2 if retained else 1}</tpRetISSQN>"
        f"</tribMun>{trib_fed}</trib></valores>"
        "</infDPS></DPS></infNFSe></NFSe>"
    )
    return xml.encode("utf-8")


def make_nfse_cancellation(
    chave: str, *, registered: bool = True, id_chave: str | None = None
) -> bytes:
    """Evento de cancelamento de NFS-e (``e101101``).

    Por padrão é o ``evento`` já processado pela autoridade (traz ``dhProc``/``nDFSe``).
    ``registered=False`` gera só o ``pedRegEvento`` (mero pedido); ``id_chave`` altera a
    chave embutida no ``Id`` do ``infEvento``.
    """
    ped = (
        '<pedRegEvento versao="1.01">'
        f'<infPedReg Id="PRE{chave}101101"><tpAmb>1</tpAmb><verAplic>SINTETICO</verAplic>'
        "<dhEvento>2026-10-12T09:00:00-03:00</dhEvento><CNPJAutor>11222333000181</CNPJAutor>"
        f"<chNFSe>{chave}</chNFSe><e101101><xDesc>Cancelamento de NFS-e</xDesc>"
        "<cMotivo>1</cMotivo><xMotivo>Erro na emissao</xMotivo></e101101>"
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
        f'<infEvento Id="EVT{id_chave or chave}101101001"><verAplic>SINTETICO</verAplic>'
        "<ambGer>1</ambGer><nSeqEvento>1</nSeqEvento><dhProc>2026-10-12T09:00:05-03:00</dhProc>"
        f"<nDFSe>1</nDFSe>{ped}</infEvento></evento>"
    )
    return xml.encode("utf-8")
