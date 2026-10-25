"""Parser de documentos fiscais: NF-e, NFS-e nacional e eventos de cancelamento.

NF-e: leiaute 4.00, namespace ``http://www.portalfiscal.inf.br/nfe`` (``nfeProc``/``NFe``).
NFS-e: padrão nacional 1.01, namespace ``http://www.sped.fazenda.gov.br/nfse`` (``NFSe``).
Os valores do XML usam ponto decimal e nunca separador de milhar.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from xml.etree.ElementTree import Element  # nosec B405

from conciliador_core.documents import cnpj_root, is_valid_cnpj, only_alnum
from conciliador_core.errors import ParseError
from conciliador_core.models import Direction, ExpectedItem, Source
from conciliador_core.money import parse_ofx_amount
from conciliador_core.parsers._xml import safe_parse_xml

NFE_NS = "http://www.portalfiscal.inf.br/nfe"
NFSE_NS = "http://www.sped.fazenda.gov.br/nfse"
_WITHHOLDINGS = ("vRetPIS", "vRetCOFINS", "vRetCSLL", "vIRRF", "vRetPrev")
# NFS-e: ordem fixa. ISS (quando retido, tpRetISSQN 2 ou 3) e as retenções federais de tribFed.
_NFSE_FEDERAL_WITHHOLDINGS = ("vRetCP", "vRetIRRF", "vRetCSLL")
_NFSE_ISS_RETAINED = ("2", "3")  # retido pelo tomador / pelo intermediário
_CANCEL_EVENT = "110111"
_REGISTERED = ("135", "155")  # cancelamento homologado (155 = fora do prazo)
# Posições 7-18 aceitam letras: CNPJ alfanumérico (padrão do XSD vigente).
_CHAVE = re.compile(r"[0-9]{6}[0-9A-Z]{12}[0-9]{26}")
# NFS-e: 3 + 50 no Id (XSD 1.01: só dígitos). As posições 10-23 são a inscrição federal, que
# aceita letras (CNPJ alfanumérico); o XSD 1.01 ainda não prevê, mas o projeto o suporta.
_NFSE_CHAVE = re.compile(r"[0-9]{9}[0-9A-Z]{14}[0-9]{27}")
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


@dataclass(frozen=True)
class FiscalParseResult:
    """Itens esperados e ids (``"nfe:<chave>"``) de notas canceladas por evento."""

    items: tuple[ExpectedItem, ...]
    cancelled_ids: tuple[str, ...]


def _invalid(message: str) -> ParseError:
    return ParseError("invalid_format", message)


def _q(path: str, ns: str = NFE_NS) -> str:
    return "/".join(f"{{{ns}}}{part}" for part in path.split("/"))


def _text(node: Element | None, path: str, ns: str = NFE_NS) -> str | None:
    if node is None:
        return None
    found = node.find(_q(path, ns))
    if found is None or found.text is None:
        return None
    return found.text.strip() or None


def _require(node: Element | None, path: str, ns: str = NFE_NS) -> str:
    value = _text(node, path, ns)
    if value is None:
        raise _invalid(f"Campo obrigatório ausente no documento fiscal: {path}.")
    return value


def _cents(text: str, field: str) -> int:
    try:
        value = parse_ofx_amount(text)
    except ParseError as exc:
        raise _invalid(f"Valor inválido em {field}: {text[:20]!r}.") from exc
    if value < 0:
        raise _invalid(f"Valor negativo em {field}.")
    return value


def _date(text: str, field: str) -> date:
    head = text.strip()[:10]
    if not _ISO_DATE.fullmatch(head):
        raise _invalid(f"Data inválida em {field}: {text[:20]!r}.")
    try:
        return date.fromisoformat(head)
    except ValueError as exc:
        raise _invalid(f"Data inválida em {field}: {text[:20]!r}.") from exc


def _add_days(day: date, days: int) -> date:
    try:
        return day + timedelta(days=days)
    except OverflowError as exc:
        raise _invalid("Vencimento fora do intervalo de datas suportado.") from exc


def _chave(text: str, field: str, pattern: re.Pattern[str] = _CHAVE) -> str:
    if not pattern.fullmatch(text):
        raise _invalid(f"Chave de acesso inválida em {field}.")
    return text


@dataclass(frozen=True)
class _Party:
    cnpj: str | None  # só CNPJ pode ser a empresa
    doc: str | None  # CNPJ ou CPF normalizado
    name: str | None


def _party(node: Element | None, ns: str = NFE_NS) -> _Party:
    cnpj = _text(node, "CNPJ", ns)
    cpf = _text(node, "CPF", ns)
    cnpj_norm = only_alnum(cnpj) if cnpj else None
    doc = cnpj_norm or (only_alnum(cpf) if cpf else None)
    return _Party(cnpj_norm, doc, _text(node, "xNome", ns))


def _is_company(party: _Party, root: str) -> bool:
    return party.cnpj is not None and len(party.cnpj) == 14 and cnpj_root(party.cnpj) == root


def _sides(
    issuer: _Party, taker: _Party, company: str, role_names: str
) -> tuple[_Party, _Party, Direction] | None:
    """Define (empresa, contraparte, direção) pela raiz do CNPJ.

    ``None`` quando a empresa está nos dois papéis (nada a conciliar); ``not_company_document``
    quando não está em nenhum. ``role_names`` só compõe a mensagem de erro.
    """
    root = cnpj_root(company)
    is_issuer, is_taker = _is_company(issuer, root), _is_company(taker, root)
    if is_issuer and is_taker:
        return None
    if not (is_issuer or is_taker):
        raise ParseError(
            "not_company_document", f"O documento não tem a empresa como {role_names}."
        )
    if is_issuer:
        return issuer, taker, Direction.INFLOW
    return taker, issuer, Direction.OUTFLOW


def _retained(entries: Iterable[tuple[str, str | None, str]]) -> tuple[tuple[str, int], ...]:
    """Retenções ``(nome, valor)`` na ordem dada; ausentes e zeradas são omitidas."""
    withheld: list[tuple[str, int]] = []
    for name, raw, field in entries:
        value = _cents(raw, field) if raw else 0
        if value:
            withheld.append((name, value))
    return tuple(withheld)


def _build_item(
    *,
    item_id: str,
    source: Source,
    direction: Direction,
    amount: int,
    due: date,
    issued: date,
    other: _Party,
    number: str | None,
    gross: int,
    withholdings: tuple[tuple[str, int], ...],
    me: _Party,
) -> ExpectedItem:
    if amount <= 0:
        raise _invalid("O valor líquido do documento fiscal deve ser maior que zero.")
    return ExpectedItem(
        id=item_id,
        source=source,
        direction=direction,
        amount_cents=amount,
        due_on=due,
        issued_on=issued,
        counterpart_doc=other.doc,
        counterpart_name=other.name,
        document_number=number,
        gross_cents=gross,
        withholdings=withholdings,
        branch_cnpj=me.cnpj,
    )


def _parse_nfe(nfe: Element, company: str, default_due_days: int) -> tuple[ExpectedItem, ...]:
    inf = nfe.find(_q("infNFe"))
    if inf is None:
        raise _invalid("NF-e sem o elemento infNFe.")
    raw_id = inf.get("Id") or ""
    if not raw_id.startswith("NFe"):
        raise _invalid("NF-e sem o atributo Id da chave de acesso.")
    chave = _chave(raw_id[3:], "infNFe/@Id")

    emit = _party(inf.find(_q("emit")))
    dest = _party(inf.find(_q("dest")))
    sides = _sides(emit, dest, company, "emitente nem como destinatária")
    if sides is None:
        return ()
    me, other, direction = sides

    ide = inf.find(_q("ide"))
    issued = _date(_text(ide, "dhEmi") or _require(ide, "dEmi"), "ide/dhEmi")
    number = _text(ide, "nNF")

    total = inf.find(_q("total"))
    gross = _cents(_require(total, "ICMSTot/vNF"), "total/ICMSTot/vNF")
    withholdings = _retained(
        (name, _text(total, f"retTrib/{name}"), f"total/retTrib/{name}") for name in _WITHHOLDINGS
    )

    def build(suffix: str, amount: int, due: date) -> ExpectedItem:
        return _build_item(
            item_id=f"nfe:{chave}:{suffix}",
            source=Source.NFE,
            direction=direction,
            amount=amount,
            due=due,
            issued=issued,
            other=other,
            number=number,
            gross=gross,
            withholdings=withholdings,
            me=me,
        )

    dups = inf.findall(_q("cobr/dup"))
    if not dups:
        net = gross - sum(v for _, v in withholdings)
        if net == 0:  # ex.: remessa de valor zero: nada a conciliar
            return ()
        return (build("1", net, _add_days(issued, default_due_days)),)

    items: list[ExpectedItem] = []
    used: set[str] = set()
    for position, dup in enumerate(dups, start=1):
        suffix = _text(dup, "nDup") or str(position)
        if suffix in used:
            suffix = f"{suffix}-{position}"
        used.add(suffix)
        due_text = _text(dup, "dVenc")
        due = _date(due_text, "cobr/dup/dVenc") if due_text else _add_days(issued, default_due_days)
        items.append(build(suffix, _cents(_require(dup, "vDup"), "cobr/dup/vDup"), due))
    return tuple(items)


def _parse_nfse(nfse: Element, company: str, default_due_days: int) -> tuple[ExpectedItem, ...]:
    inf = nfse.find(_q("infNFSe", NFSE_NS))
    if inf is None:
        raise _invalid("NFS-e sem o elemento infNFSe.")
    raw_id = inf.get("Id") or ""
    if not raw_id.startswith("NFS"):
        raise _invalid("NFS-e sem o atributo Id da chave de acesso.")
    chave = _chave(raw_id[3:], "infNFSe/@Id", _NFSE_CHAVE)

    dps = inf.find(_q("DPS/infDPS", NFSE_NS))
    if dps is None:
        raise _invalid("NFS-e sem o elemento DPS/infDPS.")
    prest = _party(dps.find(_q("prest", NFSE_NS)), NFSE_NS)
    toma = _party(dps.find(_q("toma", NFSE_NS)), NFSE_NS)  # tomador é opcional
    sides = _sides(prest, toma, company, "prestadora nem como tomadora")
    if sides is None:
        return ()
    me, other, direction = sides

    issued = _date(_require(dps, "dhEmi", NFSE_NS), "DPS/infDPS/dhEmi")
    gross = _cents(_require(dps, "valores/vServPrest/vServ", NFSE_NS), "valores/vServPrest/vServ")

    def txt(node: Element | None, path: str) -> str | None:
        return _text(node, path, NFSE_NS)

    valores = inf.find(_q("valores", NFSE_NS))
    iss_retained = txt(dps, "valores/trib/tribMun/tpRetISSQN") in _NFSE_ISS_RETAINED
    withholdings = _retained(
        [("vISSQN", txt(valores, "vISSQN") if iss_retained else None, "valores/vISSQN")]
        + [
            (name, txt(dps, f"valores/trib/tribFed/{name}"), f"valores/trib/tribFed/{name}")
            for name in _NFSE_FEDERAL_WITHHOLDINGS
        ]
    )
    liq = txt(valores, "vLiq")
    if liq:
        net = _cents(liq, "valores/vLiq")
    else:
        if iss_retained and not txt(valores, "vISSQN"):
            raise _invalid(
                "ISSQN retido sem valores/vISSQN e sem valores/vLiq: valor líquido indeterminado."
            )
        net = gross - sum(v for _, v in withholdings)
    if net == 0:
        return ()
    return (
        _build_item(
            item_id=f"nfse:{chave}:1",
            source=Source.NFSE,
            direction=direction,
            amount=net,
            due=_add_days(issued, default_due_days),
            issued=issued,
            other=other,
            number=txt(inf, "nNFSe"),
            gross=gross,
            withholdings=withholdings,
            me=me,
        ),
    )


def _parse_nfse_event(root: Element) -> tuple[str, ...]:
    """Cancelamento (``e101101``) de NFS-e.

    O ``evento`` (com ``infEvento/dhProc``, gerado pela autoridade ao registrar) é o evento
    registrado; um ``pedRegEvento`` solto é só o pedido e não cancela. O leiaute do evento não
    traz ``cStat``: o registro é indicado pela existência do ``evento`` processado.
    """
    if root.tag == _q("pedRegEvento", NFSE_NS):
        return ()
    info = root.find(_q("infEvento", NFSE_NS))
    if info is None:
        raise _invalid("Evento sem o elemento infEvento.")
    pedido = info.find(_q("pedRegEvento/infPedReg", NFSE_NS))
    if pedido is None:
        raise _invalid("Evento sem o elemento pedRegEvento/infPedReg.")
    if pedido.find(_q("e101101", NFSE_NS)) is None:
        return ()
    chave = _chave(_require(pedido, "chNFSe", NFSE_NS), "infPedReg/chNFSe", _NFSE_CHAVE)
    if _text(info, "dhProc", NFSE_NS) is None:
        return ()
    event_id = info.get("Id") or ""
    if not event_id.startswith("EVT"):
        raise _invalid("Evento sem o atributo Id (EVT + chave de acesso).")
    if event_id[3:53] != chave:
        return ()
    return (f"nfse:{chave}",)


def _parse_event(root: Element) -> tuple[str, ...]:
    info = root.find(_q("evento/infEvento"))
    if info is None:
        raise _invalid("Evento sem o elemento infEvento.")
    if _text(info, "tpEvento") != _CANCEL_EVENT:
        return ()
    chave = _chave(_require(info, "chNFe"), "infEvento/chNFe")
    # Só o retorno homologado da SEFAZ cancela: um pedido de cancelamento sem retEvento não vale.
    ret = root.find(_q("retEvento/infEvento"))
    if ret is None or _text(ret, "cStat") not in _REGISTERED:
        return ()
    ret_chave = _text(ret, "chNFe")
    if ret_chave is not None and ret_chave != chave:
        return ()
    return (f"nfe:{chave}",)


def parse_fiscal_xml(
    data: bytes, company_cnpj: str, default_due_days: int = 30
) -> FiscalParseResult:
    """Lê NF-e (``nfeProc``/``NFe``), NFS-e nacional (``NFSe``) ou evento de cancelamento.

    ``company_cnpj`` é o CNPJ da empresa (formatado ou não) e **deve ser válido**: um valor
    inválido é erro de programação de quem chama e levanta ``ValueError``. A comparação com
    emitente/destinatário é feita pela raiz do CNPJ.

    Levanta ``ParseError`` (``too_large``, ``xml_forbidden``, ``invalid_format``,
    ``unsupported_document`` ou ``not_company_document``) para qualquer problema no arquivo.
    """
    company = only_alnum(company_cnpj)
    if not is_valid_cnpj(company):
        raise ValueError("company_cnpj deve ser um CNPJ válido")
    root = safe_parse_xml(data)
    tag = root.tag
    if tag == _q("NFSe", NFSE_NS):
        return FiscalParseResult(_parse_nfse(root, company, default_due_days), ())
    if tag in (_q("evento", NFSE_NS), _q("pedRegEvento", NFSE_NS)):
        return FiscalParseResult((), _parse_nfse_event(root))
    if tag == _q("procEventoNFe"):
        return FiscalParseResult((), _parse_event(root))
    if tag == _q("nfeProc"):
        nfe = root.find(_q("NFe"))
    elif tag == _q("NFe"):
        nfe = root
    else:
        raise ParseError(
            "unsupported_document",
            "Documento fiscal não reconhecido (esperado NF-e, NFS-e nacional ou evento).",
        )
    if nfe is None:
        raise _invalid("nfeProc sem o elemento NFe.")
    return FiscalParseResult(_parse_nfe(nfe, company, default_due_days), ())
