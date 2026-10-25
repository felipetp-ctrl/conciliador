"""Gerador de arquivos OFX sintéticos (SGML v1 e XML v2) para testes."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from html import escape
from typing import Literal


@dataclass(frozen=True)
class SynthTxn:
    """Lançamento sintético. `amount_cents` é inteiro em centavos (negativo = débito)."""

    posted_on: date
    amount_cents: int
    memo: str
    fitid: str | None = None


def _fmt_amount(cents: int, decimal_comma: bool) -> str:
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(cents), 100)
    sep = "," if decimal_comma else "."
    return f"{sign}{whole}{sep}{frac:02d}"


def _fmt_date(d: date) -> str:
    return d.strftime("%Y%m%d") + "120000"


def make_ofx(
    txns: Sequence[SynthTxn],
    *,
    version: Literal[1, 2] = 1,
    encoding: Literal["cp1252", "utf-8"] = "cp1252",
    declared_charset: str | None = None,
    decimal_comma: bool = False,
    ledger_balance_cents: int | None = None,
    start: date | None = None,
    end: date | None = None,
    bank_id: str = "0341",
    branch: str = "1234",
    account: str = "56789-0",
    omit_optional: bool = False,
) -> bytes:
    """Gera um extrato OFX sintético.

    Na v1 (SGML), `declared_charset` substitui o `CHARSET` do cabeçalho; na v2 (XML),
    substitui o `encoding` do prólogo XML. Os bytes são codificados em `encoding`.
    """
    xml = version == 2

    def leaf(tag: str, value: str) -> str:
        text = escape(value, quote=False)
        return f"<{tag}>{text}</{tag}>" if xml else f"<{tag}>{text}"

    def open_(tag: str) -> str:
        return f"<{tag}>"

    def close(tag: str) -> str:
        return f"</{tag}>"

    lines: list[str] = []
    if xml:
        charset_xml = declared_charset or encoding
        lines.append(f'<?xml version="1.0" encoding="{charset_xml}"?>')
        lines.append(
            '<?OFX OFXHEADER="200" VERSION="220" SECURITY="NONE" '
            'OLDFILEUID="NONE" NEWFILEUID="NONE"?>'
        )
    else:
        default_charset = "1252" if encoding == "cp1252" else "UTF-8"
        lines += [
            "OFXHEADER:100",
            "DATA:OFXSGML",
            "VERSION:102",
            "SECURITY:NONE",
            f"ENCODING:{'USASCII' if encoding == 'cp1252' else 'UTF-8'}",
            f"CHARSET:{declared_charset or default_charset}",
            "COMPRESSION:NONE",
            "OLDFILEUID:NONE",
            "NEWFILEUID:NONE",
            "",
        ]

    lines += [
        open_("OFX"),
        open_("SIGNONMSGSRSV1"),
        open_("SONRS"),
        open_("STATUS"),
        leaf("CODE", "0"),
        leaf("SEVERITY", "INFO"),
        close("STATUS"),
        leaf("DTSERVER", "20261024120000"),
        leaf("LANGUAGE", "POR"),
        close("SONRS"),
        close("SIGNONMSGSRSV1"),
        open_("BANKMSGSRSV1"),
        open_("STMTTRNRS"),
        leaf("TRNUID", "1"),
        open_("STATUS"),
        leaf("CODE", "0"),
        leaf("SEVERITY", "INFO"),
        close("STATUS"),
        open_("STMTRS"),
        leaf("CURDEF", "BRL"),
        open_("BANKACCTFROM"),
        leaf("BANKID", bank_id),
        leaf("BRANCHID", branch),
        leaf("ACCTID", account),
        leaf("ACCTTYPE", "CHECKING"),
        close("BANKACCTFROM"),
        open_("BANKTRANLIST"),
    ]
    if not omit_optional:
        first = start or (min(t.posted_on for t in txns) if txns else None)
        last = end or (max(t.posted_on for t in txns) if txns else None)
        if first is not None:
            lines.append(leaf("DTSTART", _fmt_date(first)))
        if last is not None:
            lines.append(leaf("DTEND", _fmt_date(last)))

    for txn in txns:
        lines += [
            open_("STMTTRN"),
            leaf("TRNTYPE", "CREDIT" if txn.amount_cents >= 0 else "DEBIT"),
            leaf("DTPOSTED", _fmt_date(txn.posted_on)),
            leaf("TRNAMT", _fmt_amount(txn.amount_cents, decimal_comma)),
        ]
        if not omit_optional and txn.fitid is not None:
            lines.append(leaf("FITID", txn.fitid))
        lines += [leaf("MEMO", txn.memo), close("STMTTRN")]

    lines.append(close("BANKTRANLIST"))
    if not omit_optional and ledger_balance_cents is not None:
        lines += [
            open_("LEDGERBAL"),
            leaf("BALAMT", _fmt_amount(ledger_balance_cents, decimal_comma)),
            leaf("DTASOF", _fmt_date(end or date(2026, 10, 24))),
            close("LEDGERBAL"),
        ]
    lines += [close("STMTRS"), close("STMTTRNRS"), close("BANKMSGSRSV1"), close("OFX")]

    text = "\r\n".join(lines) + "\r\n"
    return text.encode(encoding)
