"""Parser OFX tolerante (SGML v1 e XML v2).

Os OFX brasileiros frequentemente violam a especificação, então o parser usa um
tokenizador próprio em vez de um parser XML. O conteúdo nunca passa por um parser
XML, logo não há superfície para XXE ou expansão de entidades.
"""

import re
from collections.abc import Iterator
from datetime import date
from html import unescape

from conciliador_core.documents import find_documents
from conciliador_core.errors import ParseError
from conciliador_core.models import BankAccountRef, BankTransaction, Statement
from conciliador_core.money import parse_brl_amount

MAX_FILE_BYTES = 10 * 1024 * 1024

# Sem aninhamento nem alternâncias sobrepostas: tempo linear na entrada.
_TOKEN = re.compile(r"<(/?)([A-Za-z0-9.]+)>([^<]*)")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SPACES = re.compile(r"\s+")
_STATEMENTS = ("STMTRS", "CCSTMTRS")
_ACCOUNTS = ("BANKACCTFROM", "CCACCTFROM")


def _invalid(message: str) -> ParseError:
    return ParseError("invalid_format", message)


def _decode(data: bytes) -> str:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        # O cabeçalho (CHARSET/encoding) costuma mentir, então é ignorado.
        text = data.decode("cp1252", errors="replace")
    return text.lstrip("﻿")


def _tokens(text: str) -> Iterator[tuple[bool, str, str]]:
    for match in _TOKEN.finditer(text):
        yield match.group(1) == "/", match.group(2).upper(), match.group(3)


def _clean(value: str) -> str:
    """Decodifica entidades HTML, remove caracteres de controle e colapsa espaços."""
    text = _CONTROL.sub(" ", unescape(value))
    return _SPACES.sub(" ", text).strip()


def _parse_date(value: str) -> date:
    head = value.strip()[:8]
    if len(head) != 8 or not head.isascii() or not head.isdigit():
        raise _invalid(f"Data inválida no OFX: {value.strip()[:20]!r}.")
    try:
        return date(int(head[:4]), int(head[4:6]), int(head[6:8]))
    except ValueError:
        raise _invalid(f"Data inválida no OFX: {head!r}.") from None


def _optional_date(value: str | None) -> date | None:
    try:
        return _parse_date(value) if value else None
    except ParseError:
        return None


def _memo(fields: dict[str, str]) -> str:
    """Monta o histórico: ``NAME MEMO`` (separados por espaço) quando ambos existem e
    diferem; caso contrário, o que existir."""
    name = fields.get("NAME", "")
    memo = fields.get("MEMO", "")
    if name and memo and name != memo:
        return f"{name} {memo}"
    return name or memo


def _transaction(fields: dict[str, str]) -> BankTransaction:
    posted_on = _parse_date(fields.get("DTPOSTED", ""))
    amount = parse_brl_amount(fields.get("TRNAMT", ""))
    memo = _memo(fields)
    return BankTransaction(
        fitid=fields.get("FITID") or None,
        posted_on=posted_on,
        amount_cents=amount,
        memo=memo,
        documents=find_documents(memo),
        dedup_key="",
    )


def parse_ofx(data: bytes) -> Statement:
    """Lê um OFX (v1 SGML ou v2 XML) e devolve o primeiro extrato (conta ou cartão).

    Se o arquivo tiver vários extratos, só o primeiro é lido. O histórico de cada
    lançamento é ``NAME MEMO`` quando ambos existem e diferem, senão o que existir.
    Qualquer entrada inválida levanta :class:`ParseError`.
    """
    if len(data) > MAX_FILE_BYTES:
        raise ParseError("too_large", "Arquivo OFX maior que o limite de 10 MB.")
    text = _decode(data)

    seen_ofx = False
    in_stmt = False
    section: str | None = None  # "acct" | "txn" | "bal"
    account: dict[str, str] = {}
    balance: dict[str, str] = {}
    head: dict[str, str] = {}
    txn_fields: dict[str, str] = {}
    transactions: list[BankTransaction] = []
    found_statement = False

    def flush_txn() -> None:
        nonlocal section
        if section == "txn":
            transactions.append(_transaction(txn_fields))
            txn_fields.clear()
            section = None

    for closing, tag, raw in _tokens(text):
        if tag == "OFX" and not closing:
            seen_ofx = True
        if not seen_ofx:
            continue
        if not in_stmt:
            if tag in _STATEMENTS and not closing:
                in_stmt = found_statement = True
            continue
        if tag in _STATEMENTS:
            flush_txn()
            break
        if tag == "STMTTRN":
            flush_txn()
            if not closing:
                section = "txn"
            continue
        if tag in _ACCOUNTS:
            flush_txn()
            section = None if closing else "acct"
            continue
        if tag == "LEDGERBAL":
            flush_txn()
            section = None if closing else "bal"
            continue
        if tag == "BANKTRANLIST" or tag == "AVAILBAL":
            flush_txn()
            section = None
            continue
        if closing:
            continue
        value = _clean(raw)
        target = {"txn": txn_fields, "acct": account, "bal": balance, None: head}.get(section)
        if target is not None and tag not in target:
            target[tag] = value
    else:
        flush_txn()

    if not seen_ofx or not found_statement:
        raise _invalid("O arquivo não é um extrato OFX válido.")

    balance_text = balance.get("BALAMT", "")
    return Statement(
        account=BankAccountRef(
            bank_id=account.get("BANKID", ""),
            branch=account.get("BRANCHID") or None,
            account_number=account.get("ACCTID", ""),
        ),
        start=_optional_date(head.get("DTSTART")),
        end=_optional_date(head.get("DTEND")),
        ledger_balance_cents=parse_brl_amount(balance_text) if balance_text else None,
        transactions=tuple(transactions),
    )
