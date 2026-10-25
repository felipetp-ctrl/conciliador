"""Ingestão de arquivos reais (corpus) para o banco, via ``conciliador_core``.

Para a demonstração local, cada arquivo é parseado com os leitores do núcleo e
gravado sob a empresa de demonstração. OFX vira conta + lançamentos; cada XML
fiscal é parseado do ponto de vista do seu emitente (direção "a receber") e os
itens ficam sob a empresa de demonstração — a segmentação por empresa real entra
junto com autenticação/RLS.
"""

from __future__ import annotations

import re
from pathlib import Path

from conciliador_core import ParseError, parse_fiscal_xml, parse_items_csv, parse_ofx

from . import models

_EMIT = re.compile(rb"<emit>.*?<CNPJ>([0-9A-Za-z]{14})</CNPJ>", re.S)
_PREST = re.compile(rb"<prest(?:ador)?>.*?<CNPJ>([0-9A-Za-z]{14})</CNPJ>", re.S)


def ingest_ofx(path: Path, company: models.Company) -> dict:
    """Parseia um OFX e grava a conta e os lançamentos. Devolve um resumo."""
    try:
        stmt = parse_ofx(path.read_bytes())
    except ParseError as e:
        return {"file": path.name, "ok": False, "error": e.code}
    account, _ = models.BankAccount.objects.get_or_create(
        company=company,
        bank_id=stmt.account.bank_id,
        branch=stmt.account.branch or "",
        account_number=stmt.account.account_number,
        defaults={"ledger_balance_cents": stmt.ledger_balance_cents},
    )
    if stmt.ledger_balance_cents is not None:
        account.ledger_balance_cents = stmt.ledger_balance_cents
        account.save(update_fields=["ledger_balance_cents"])
    created = 0
    for t in stmt.transactions:
        _, was_created = models.BankTransaction.objects.get_or_create(
            account=account,
            dedup_key=t.dedup_key,
            defaults={
                "fitid": t.fitid or "",
                "posted_on": t.posted_on,
                "amount_cents": t.amount_cents,
                "memo": t.memo,
                "documents": list(t.documents),
            },
        )
        created += int(was_created)
    return {
        "file": path.name,
        "ok": True,
        "txns": len(stmt.transactions),
        "created": created,
        "account": account.label,
    }


def _save_item(item, company: models.Company, status: str) -> bool:
    """Grava (ou atualiza) um item esperado do núcleo. Devolve True se criou."""
    _, created = models.ExpectedItem.objects.update_or_create(
        external_id=item.id,
        defaults={
            "company": company,
            "source": item.source.value,
            "direction": item.direction.value,
            "amount_cents": item.amount_cents,
            "due_on": item.due_on,
            "issued_on": item.issued_on,
            "counterpart_doc": item.counterpart_doc or "",
            "counterpart_name": item.counterpart_name or "",
            "document_number": item.document_number or "",
            "gross_cents": item.gross_cents,
            "withholdings": [[name, cents] for name, cents in item.withholdings],
            "status": status,
        },
    )
    return created


def ingest_fiscal(path: Path, company: models.Company) -> dict:
    """Parseia um XML fiscal do ponto de vista do emitente e grava os itens."""
    data = path.read_bytes()
    m = _EMIT.search(data) or _PREST.search(data)
    if not m:
        return {"file": path.name, "ok": False, "error": "no_emitente"}
    company_cnpj = m.group(1).decode()
    try:
        result = parse_fiscal_xml(data, company_cnpj)
    except ParseError as e:
        return {"file": path.name, "ok": False, "error": e.code}
    except ValueError:
        return {"file": path.name, "ok": False, "error": "invalid_cnpj"}
    created = 0
    cancelled = set(result.cancelled_ids)
    for item in result.items:
        status = "cancelled" if any(item.id.startswith(c + ":") for c in cancelled) else "open"
        created += int(_save_item(item, company, status))
    return {
        "file": path.name,
        "ok": True,
        "items": len(result.items),
        "created": created,
        "emitente": company_cnpj,
    }


def ingest_csv(path: Path, company: models.Company) -> dict:
    """Parseia um CSV de contas a pagar/receber e grava os itens válidos."""
    try:
        result = parse_items_csv(path.read_bytes())
    except ParseError as e:
        return {"file": path.name, "ok": False, "error": e.code}
    created = sum(int(_save_item(item, company, "open")) for item in result.items)
    return {
        "file": path.name,
        "ok": True,
        "items": len(result.items),
        "created": created,
        "errors": len(result.errors),
    }


def ingest_corpus(corpus_dir: str, company: models.Company) -> list[dict]:
    """Ingere todo o corpus (OFX + XML fiscais). Devolve o relatório por arquivo."""
    root = Path(corpus_dir)
    report: list[dict] = []
    for path in sorted((root / "ofx").glob("*.ofx")):
        report.append(ingest_ofx(path, company))
    for sub in ("nfe", "nfse-nacional"):
        folder = root / sub
        if folder.exists():
            for path in sorted(folder.glob("*.xml")):
                report.append(ingest_fiscal(path, company))
    return report
