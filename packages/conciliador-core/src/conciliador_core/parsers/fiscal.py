"""Parser de documentos fiscais: NF-e (``nfeProc``/``NFe``) e eventos de cancelamento.

Leiaute 4.00 da NF-e, namespace ``http://www.portalfiscal.inf.br/nfe``. Os valores do XML
usam ponto decimal e nunca separador de milhar.
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta
from xml.etree.ElementTree import Element  # nosec B405

from conciliador_core.documents import cnpj_root, is_valid_cnpj, only_alnum
from conciliador_core.errors import ParseError
from conciliador_core.models import Direction, ExpectedItem, Source
from conciliador_core.money import parse_ofx_amount
from conciliador_core.parsers._xml import safe_parse_xml

NFE_NS = "http://www.portalfiscal.inf.br/nfe"
_WITHHOLDINGS = ("vRetPIS", "vRetCOFINS", "vRetCSLL", "vIRRF", "vRetPrev")
_CANCEL_EVENT = "110111"
_REGISTERED = ("135", "155")  # cancelamento homologado (155 = fora do prazo)
# Posições 7-18 aceitam letras: CNPJ alfanumérico (padrão do XSD vigente).
_CHAVE = re.compile(r"[0-9]{6}[0-9A-Z]{12}[0-9]{26}")
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


@dataclass(frozen=True)
class FiscalParseResult:
    """Itens esperados e ids (``"nfe:<chave>"``) de notas canceladas por evento."""

    items: tuple[ExpectedItem, ...]
    cancelled_ids: tuple[str, ...]


def _invalid(message: str) -> ParseError:
    return ParseError("invalid_format", message)


def _q(path: str) -> str:
    return "/".join(f"{{{NFE_NS}}}{part}" for part in path.split("/"))


def _text(node: Element | None, path: str) -> str | None:
    if node is None:
        return None
    found = node.find(_q(path))
    if found is None or found.text is None:
        return None
    return found.text.strip() or None


def _require(node: Element | None, path: str) -> str:
    value = _text(node, path)
    if value is None:
        raise _invalid(f"Campo obrigatório ausente na NF-e: {path}.")
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


def _chave(text: str, field: str) -> str:
    if not _CHAVE.fullmatch(text):
        raise _invalid(f"Chave de acesso inválida em {field}.")
    return text


@dataclass(frozen=True)
class _Party:
    cnpj: str | None  # só CNPJ pode ser a empresa
    doc: str | None  # CNPJ ou CPF normalizado
    name: str | None


def _party(node: Element | None) -> _Party:
    cnpj = _text(node, "CNPJ")
    cpf = _text(node, "CPF")
    cnpj_norm = only_alnum(cnpj) if cnpj else None
    doc = cnpj_norm or (only_alnum(cpf) if cpf else None)
    return _Party(cnpj_norm, doc, _text(node, "xNome"))


def _is_company(party: _Party, root: str) -> bool:
    return party.cnpj is not None and len(party.cnpj) == 14 and cnpj_root(party.cnpj) == root


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
    root = cnpj_root(company)
    is_emit, is_dest = _is_company(emit, root), _is_company(dest, root)
    if is_emit and is_dest:
        return ()
    if not (is_emit or is_dest):
        raise ParseError(
            "not_company_document",
            "O documento não tem a empresa como emitente nem como destinatária.",
        )
    me, other = (emit, dest) if is_emit else (dest, emit)
    direction = Direction.INFLOW if is_emit else Direction.OUTFLOW

    ide = inf.find(_q("ide"))
    issued = _date(_text(ide, "dhEmi") or _require(ide, "dEmi"), "ide/dhEmi")
    number = _text(ide, "nNF")

    total = inf.find(_q("total"))
    gross = _cents(_require(total, "ICMSTot/vNF"), "total/ICMSTot/vNF")
    withheld: list[tuple[str, int]] = []
    for name in _WITHHOLDINGS:
        raw = _text(total, f"retTrib/{name}")
        value = _cents(raw, f"total/retTrib/{name}") if raw else 0
        if value:
            withheld.append((name, value))
    withholdings = tuple(withheld)

    def build(suffix: str, amount: int, due: date) -> ExpectedItem:
        if amount <= 0:
            raise _invalid("O valor líquido da NF-e deve ser maior que zero.")
        return ExpectedItem(
            id=f"nfe:{chave}:{suffix}",
            source=Source.NFE,
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
    """Lê uma NF-e (``nfeProc`` ou ``NFe``) ou um ``procEventoNFe`` de cancelamento.

    ``company_cnpj`` é o CNPJ da empresa (formatado ou não) e **deve ser válido**: um valor
    inválido é erro de programação de quem chama e levanta ``ValueError``. A comparação com
    emitente/destinatário é feita pela raiz do CNPJ.

    Levanta ``ParseError`` (``too_large``, ``xml_forbidden``, ``invalid_format`` ou
    ``not_company_document``) para qualquer problema no arquivo.
    """
    company = only_alnum(company_cnpj)
    if not is_valid_cnpj(company):
        raise ValueError("company_cnpj deve ser um CNPJ válido")
    root = safe_parse_xml(data)
    tag = root.tag
    if tag == _q("procEventoNFe"):
        return FiscalParseResult((), _parse_event(root))
    if tag == _q("nfeProc"):
        nfe = root.find(_q("NFe"))
    elif tag == _q("NFe"):
        nfe = root
    else:
        raise _invalid("Documento fiscal não reconhecido (esperado nfeProc, NFe ou procEventoNFe).")
    if nfe is None:
        raise _invalid("nfeProc sem o elemento NFe.")
    return FiscalParseResult(_parse_nfe(nfe, company, default_due_days), ())
