"""Gerador de XMLs fiscais sintéticos (NF-e e evento de cancelamento) para testes.

Os documentos seguem os nomes e caminhos do leiaute 4.00 da NF-e, mas contêm apenas o
subconjunto lido pelo parser (não são válidos contra o XSD completo).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from html import escape

NFE_NS = "http://www.portalfiscal.inf.br/nfe"
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
