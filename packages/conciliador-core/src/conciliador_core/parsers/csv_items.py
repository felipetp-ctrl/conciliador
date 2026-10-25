"""Importação de contas a pagar e a receber a partir de CSV."""

import csv
import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from importlib import resources

from conciliador_core.dedup import encode_fields
from conciliador_core.documents import is_valid_cnpj, is_valid_cpf, only_alnum
from conciliador_core.errors import ParseError
from conciliador_core.models import Direction, ExpectedItem, Source
from conciliador_core.money import parse_brl_amount
from conciliador_core.parsers._limits import MAX_FILE_BYTES

MAX_ROWS = 10_000
_REQUIRED = ("tipo", "valor", "vencimento")
_OPTIONAL = ("contraparte_nome", "contraparte_documento", "documento_numero", "descricao")
_KNOWN = _REQUIRED + _OPTIONAL
_DATE = re.compile(r"([0-9]{2})/([0-9]{2})/([0-9]{4})", re.ASCII)
_CURRENCY = re.compile(r"R\$\s*", re.IGNORECASE)
_NEWLINE = re.compile(r"\r\n|\r|\n")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_DIRECTIONS = {"receber": Direction.INFLOW, "pagar": Direction.OUTFLOW}


@dataclass(frozen=True)
class RowError:
    line: int
    message: str


@dataclass(frozen=True)
class CsvParseResult:
    items: tuple[ExpectedItem, ...]
    errors: tuple[RowError, ...]


def _decode(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _normalize_header(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name.strip().lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _parse_due(text: str) -> date | None:
    m = _DATE.fullmatch(text)
    if not m:
        return None
    year = int(m.group(3))
    if not 2000 <= year <= 2099:
        return None
    try:
        return date(year, int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _build_item(cells: dict[str, str]) -> ExpectedItem | str:
    direction = _DIRECTIONS.get(_normalize_header(cells["tipo"]))
    if direction is None:
        return "tipo deve ser receber ou pagar"
    try:
        amount = parse_brl_amount(_CURRENCY.sub("", cells["valor"], count=1))
    except ParseError:
        return "valor inválido"
    if amount <= 0:
        return "valor deve ser positivo"
    due = _parse_due(cells["vencimento"])
    if due is None:
        return "vencimento inválido: use DD/MM/AAAA"
    doc = only_alnum(cells["contraparte_documento"])
    if doc and not (is_valid_cpf(doc) or is_valid_cnpj(doc)):
        return "documento inválido"
    name = cells["contraparte_nome"]
    number = cells["documento_numero"]
    digest = hashlib.sha256(
        encode_fields(
            [
                direction.value,
                str(amount),
                due.isoformat(),
                doc,
                name,
                number,
                cells["descricao"],
            ]
        ).encode("utf-8")
    ).hexdigest()
    return ExpectedItem(
        id=f"csv:{digest[:16]}",
        source=Source.CSV,
        direction=direction,
        amount_cents=amount,
        due_on=due,
        issued_on=None,
        counterpart_doc=doc or None,
        counterpart_name=name or None,
        document_number=number or None,
    )


def _read_header(record: list[str]) -> dict[str, int]:
    columns: dict[str, int] = {}
    for idx, raw in enumerate(record):
        name = _normalize_header(raw)
        if name not in _KNOWN:
            continue
        if name in columns:
            raise ParseError("invalid_format", f"Cabeçalho do CSV com a coluna repetida: {name}.")
        columns[name] = idx
    missing = [c for c in _REQUIRED if c not in columns]
    if missing:
        raise ParseError(
            "invalid_format", f"Cabeçalho do CSV sem coluna obrigatória: {', '.join(missing)}."
        )
    return columns


def parse_items_csv(data: bytes) -> CsvParseResult:
    """Lê um CSV de contas a pagar/receber. Linhas inválidas vão para ``errors``."""
    if len(data) > MAX_FILE_BYTES:
        raise ParseError("too_large", "Arquivo CSV maior que o limite de 10 MB.")
    text = _decode(data)
    first_line = next((ln for ln in _NEWLINE.split(text) if ln.strip()), "")
    if not first_line:
        return CsvParseResult((), ())
    delimiter = ";" if first_line.count(";") >= first_line.count(",") else ","

    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    items: list[ExpectedItem] = []
    errors: list[RowError] = []
    seen: set[str] = set()
    columns: dict[str, int] | None = None
    rows = 0
    previous_line = 0
    try:
        for record in reader:
            line = previous_line + 1
            previous_line = reader.line_num
            if not any(c.strip() for c in record):
                continue
            if columns is None:
                columns = _read_header(record)
                continue
            rows += 1
            if rows > MAX_ROWS:
                raise ParseError("too_large", f"CSV com mais de {MAX_ROWS} linhas de dados.")
            if any("\n" in c or "\r" in c for c in record):
                errors.append(RowError(line, "campo com quebra de linha — verifique aspas"))
                continue
            cells = {
                name: _CONTROL.sub("", record[idx]).strip()
                if idx is not None and idx < len(record)
                else ""
                for name, idx in ((n, columns.get(n)) for n in _KNOWN)
            }
            built = _build_item(cells)
            if isinstance(built, str):
                errors.append(RowError(line, built))
            elif built.id in seen:
                errors.append(RowError(line, "linha duplicada"))
            else:
                seen.add(built.id)
                items.append(built)
    except csv.Error as exc:
        raise ParseError("invalid_format", f"CSV malformado: {exc}") from exc
    return CsvParseResult(tuple(items), tuple(errors))


def template_csv() -> bytes:
    """Modelo de planilha (CSV com `;`, UTF-8 com BOM) para importação."""
    return resources.files("conciliador_core").joinpath("templates/contas.csv").read_bytes()
