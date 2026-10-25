"""Constrói o contexto de conciliação (ReconItems, totais, conciliação de saldo).

Aqui os modelos do Django viram os dataclasses do núcleo, o ``RuleBasedProvider`` gera as
sugestões 1:1, o ``find_group_suggestions`` completa com N:N (parcelas e remessas) e o
``reconcile_balances`` monta a conciliação bancária de saldo: razão derivada dos documentos
contra o extrato, com a diferença explicada. Dinheiro sempre em centavos inteiros.
"""

from __future__ import annotations

from conciliador_core import (
    BankTransaction as CoreBankTransaction,
)
from conciliador_core import (
    ExpectedItem as CoreExpectedItem,
)
from conciliador_core import (
    ItemStatus,
    MatchConfig,
    Rule,
    RuleBasedProvider,
    classify_item,
    find_group_suggestions,
    reconcile_balances,
)
from conciliador_core.engine.reconciliation import LedgerLine
from conciliador_core.models import Direction, Source
from conciliador_ui import vocab
from django.db.models import Max

from . import models

RULE_LABEL = {
    Rule.DOCUMENT: "Regra 1",
    Rule.NUMBER: "Regra 2",
    Rule.UNIQUE: "Regra 3",
    Rule.AMBIGUOUS: "Regra 3",
    Rule.PARTIAL: "Parcela",
    Rule.BATCH: "Remessa",
}
KIND = {Source.NFE: "NF-e", Source.NFSE: "NFS-e", Source.CSV: "CSV", Source.MANUAL: "Manual"}
DIR = {Direction.INFLOW: "in", Direction.OUTFLOW: "out"}
ORDER = vocab.ORDER

# Classificações de um lançamento "só no banco". ``direction`` é "in"/"out"; ``None`` para
# transferência (neutra) e para "outro" (a pessoa escolhe a direção).
CLASSIFICATIONS: dict[str, dict] = {
    "tarifa": {"label": "Tarifa bancária", "direction": "out"},
    "juros": {"label": "Juros", "direction": "out"},
    "multa": {"label": "Multa", "direction": "out"},
    "iof": {"label": "IOF", "direction": "out"},
    "imposto": {"label": "Imposto", "direction": "out"},
    "pro_labore": {"label": "Pró-labore", "direction": "out"},
    "rendimento": {"label": "Rendimento", "direction": "in"},
    "aporte": {"label": "Aporte do sócio", "direction": "in"},
    "transferencia": {"label": "Transferência entre contas", "direction": None},
    "outro": {"label": "Outro", "direction": None},
}


def _to_core_tx(t: models.BankTransaction) -> CoreBankTransaction:
    return CoreBankTransaction(
        fitid=t.fitid or None,
        posted_on=t.posted_on,
        amount_cents=t.amount_cents,
        memo=t.memo,
        documents=tuple(t.documents or ()),
        dedup_key=t.dedup_key or "",
    )


def _to_core_item(i: models.ExpectedItem) -> CoreExpectedItem:
    return CoreExpectedItem(
        id=i.external_id,
        source=Source(i.source),
        direction=Direction(i.direction),
        amount_cents=i.amount_cents,
        due_on=i.due_on,
        issued_on=i.issued_on,
        counterpart_doc=i.counterpart_doc or None,
        counterpart_name=i.counterpart_name or None,
        document_number=i.document_number or None,
        gross_cents=i.gross_cents,
        withholdings=tuple((name, cents) for name, cents in (i.withholdings or ())),
        status=ItemStatus(i.status),
    )


def _facts(reason: str) -> list[str]:
    return [p.strip() for p in reason.split(";") if p.strip()]


def _doc_side(i: models.ExpectedItem) -> dict:
    direction = DIR[Direction(i.direction)]
    cents = i.amount_cents if direction == "in" else -i.amount_cents
    withheld = sum(c for _, c in (i.withholdings or ()))
    return {
        "id": i.pk,
        "kind": KIND[Source(i.source)],
        "number": i.document_number,
        "counterpart": i.counterpart_name or "",
        "doc_id": i.counterpart_doc,
        "due": i.due_on,
        "issued": i.issued_on,
        "cents": cents,
        "gross_cents": i.gross_cents,
        "withheld_cents": withheld,
    }


def _bank_side(t: models.BankTransaction) -> dict:
    return {
        "id": t.pk,
        "account_id": t.account_id,
        "date": t.posted_on,
        "memo": t.memo,
        "cents": t.amount_cents,
        "account": t.account.label,
        "raw": t.memo,
        "fitid": t.fitid,
    }


def _date_fact(posted_on, due_on) -> str:
    days = (posted_on - due_on).days
    if days == 0:
        return "no dia do vencimento"
    if days > 0:
        return f"{days} dia{'s' if days != 1 else ''} após o vencimento"
    return f"{-days} dia{'s' if days != -1 else ''} antes do vencimento"


def _doc_signed(i: models.ExpectedItem) -> int:
    return i.amount_cents if i.direction == "inflow" else -i.amount_cents


def _settled_group(links: list[models.Link], direction: str) -> dict:
    """Um componente conexo de vínculos confirmados (1:1, parcela ou remessa)."""
    txns = sorted({ln.transaction for ln in links}, key=lambda t: (t.posted_on, t.pk))
    items = sorted({ln.item for ln in links}, key=lambda i: (i.due_on, i.pk))
    bank_signed = sum(t.amount_cents for t in txns)
    doc_signed = sum(_doc_signed(i) for i in items)
    gap_signed = doc_signed - bank_signed
    is_div = any(ln.closed_with_difference for ln in links) or gap_signed != 0

    facts: list[str] = ["vínculo confirmado"]
    facts += [_date_fact(t.posted_on, i.due_on) for t, i in _pairs(links)]
    facts = list(dict.fromkeys(facts))  # sem repetir "no dia do vencimento"

    first = links[0]
    signed_by = f"confirmado por {first.created_by or 'você'} · {first.created_at:%d/%m %H:%M}"
    bank_side = _bank_side(txns[0]) if len(txns) == 1 else None
    doc_side = _doc_side(items[0]) if len(items) == 1 else None

    item = {
        "id": f"lk:{first.pk}",
        "status": "divergencia" if is_div else "conciliado",
        "direction": direction,
        "kind": None
        if len(txns) == len(items) == 1
        else ("batch" if len(items) > 1 else "partial"),
        "rule": "Manual" if first.rule == "manual" else RULE_LABEL.get(Rule(first.rule), "Regra 1"),
        "facts": facts,
        "signed_by": signed_by,
        "audit": [
            {
                "at": first.created_at,
                "action": "Vínculo confirmado",
                "who": first.created_by or "você",
            }
        ],
        "bank": bank_side,
        "doc": doc_side,
        "bank_many": [_bank_side(t) for t in txns] if len(txns) > 1 else None,
        "doc_many": [_doc_side(i) for i in items] if len(items) > 1 else None,
        "candidates": None,
        "cents": doc_signed,
        "diff_cents": gap_signed,
        "gap_signed": gap_signed,
    }
    if is_div:
        bank_mag = sum(abs(t.amount_cents) for t in txns)
        doc_mag = sum(i.amount_cents for i in items)
        gap = abs(bank_mag - doc_mag)
        gap_txt = f"{gap // 100},{gap % 100:02d}"
        more = "a mais" if bank_mag > doc_mag else "a menos"
        item["diff_title"] = f"{'Recebido' if direction == 'in' else 'Pago'} {gap_txt} {more}"
        due_txt = ", ".join(f"{i.due_on:%d/%m/%Y}" for i in items)
        item["diff_reason"] = (
            f"O extrato registrou R$ {gap_txt} {more} que o documento (vencimento {due_txt})."
        )
    return item


def _pairs(links: list[models.Link]) -> list[tuple]:
    return [(ln.transaction, ln.item) for ln in links]


def _connected_links(links: list[models.Link]) -> list[list[models.Link]]:
    """Agrupa vínculos que compartilham lançamento ou item (componentes conexos)."""
    by_tx: dict[int, list[models.Link]] = {}
    by_item: dict[int, list[models.Link]] = {}
    for link in links:
        by_tx.setdefault(link.transaction_id, []).append(link)
        by_item.setdefault(link.item_id, []).append(link)

    groups: list[list[models.Link]] = []
    seen: set[int] = set()
    for link in links:
        if link.pk in seen:
            continue
        stack = [link]
        group: list[models.Link] = []
        while stack:
            cur = stack.pop()
            if cur.pk in seen:
                continue
            seen.add(cur.pk)
            group.append(cur)
            for nxt in by_tx[cur.transaction_id]:
                if nxt.pk not in seen:
                    stack.append(nxt)
            for nxt in by_item[cur.item_id]:
                if nxt.pk not in seen:
                    stack.append(nxt)
        groups.append(group)
    return groups


def unlink_group(link: models.Link) -> int:
    """Apaga um vínculo e todos os do mesmo grupo (parcela/remessa). Devolve a conta."""
    links = list(models.Link.objects.filter(company=link.company).select_related("transaction"))
    target = next((g for g in _connected_links(links) if any(ln.pk == link.pk for ln in g)), [link])
    conta_id = link.transaction.account_id
    models.Link.objects.filter(pk__in=[ln.pk for ln in target]).delete()
    return conta_id


def reconcile(
    company: models.Company,
    account: models.BankAccount | None = None,
    period: models.Period | None = None,
) -> dict:
    """Contexto completo do painel para uma empresa (e, se dadas, uma conta e um período)."""
    qs = models.BankTransaction.objects.filter(account__company=company)
    if account is not None:
        qs = qs.filter(account=account)
    if period is not None:
        qs = qs.filter(posted_on__gte=period.start, posted_on__lte=period.end)
    txns = list(qs.select_related("account").order_by("posted_on", "id"))
    items = list(models.ExpectedItem.objects.filter(company=company).order_by("due_on", "id"))

    # Vínculos: os do período entram na conciliação; os demais só servem para não
    # oferecer de novo um item que já foi baixado em outro mês.
    all_links = list(
        models.Link.objects.filter(company=company).select_related(
            "transaction", "item", "transaction__account"
        )
    )
    tx_ids = {t.pk for t in txns}
    links = [
        ln
        for group in _connected_links(all_links)
        if all(ln.transaction_id in tx_ids for ln in group)
        for ln in group
    ]

    linked_tx_ids = {ln.transaction_id for ln in all_links}
    linked_item_ids = {ln.item_id for ln in all_links}

    # Partição dos lançamentos do extrato.
    classified = [t for t in txns if t.is_classified and t.classification != "transferencia"]
    transfers = [t for t in txns if t.is_classified and t.classification == "transferencia"]
    matchable = [t for t in txns if t.pk not in linked_tx_ids and not t.is_classified]
    matchable_items = [i for i in items if i.pk not in linked_item_ids and i.status == "open"]

    # 1:1
    provider = RuleBasedProvider()
    config = MatchConfig()
    rejected = frozenset(
        (r.transaction.dedup_key, r.item.external_id)
        for r in models.RejectedLink.objects.filter(company=company).select_related(
            "transaction", "item"
        )
    )
    suggestions = provider.suggest(
        [_to_core_tx(t) for t in matchable],
        [_to_core_item(i) for i in matchable_items],
        config,
        rejected=rejected,
    )
    primary_by_tx: dict[str, list] = {}
    ambiguous_by_tx: dict[str, list] = {}
    for s in suggestions:
        (primary_by_tx if s.is_primary else ambiguous_by_tx).setdefault(
            s.transaction_key, []
        ).append(s)

    suggested_tx_keys = {s.transaction_key for s in suggestions}
    suggested_item_ids = {s.item_id for s in suggestions}

    # N:N sobre o que sobrou do 1:1
    leftover_txns = [t for t in matchable if t.dedup_key not in suggested_tx_keys]
    leftover_items = [i for i in matchable_items if i.external_id not in suggested_item_ids]
    groups = find_group_suggestions(
        [_to_core_tx(t) for t in leftover_txns],
        [_to_core_item(i) for i in leftover_items],
        config,
    )

    tx_by_key = {t.dedup_key or f"pk{t.pk}": t for t in matchable}
    item_by_ext = {i.external_id: i for i in items}
    item_direction = {i.external_id: DIR[Direction(i.direction)] for i in items}

    recon: list[dict] = []
    used_tx: set[str] = set()
    used_item: set[str] = set()

    # 1. vínculos confirmados (1:1, parcela, remessa)
    for group in _connected_links(links):
        for link in group:
            used_tx.add(link.transaction.dedup_key or f"pk{link.transaction_id}")
            used_item.add(link.item.external_id)
        recon.append(_settled_group(group, item_direction[group[0].item.external_id]))

    # 2. sugestões primárias → a confirmar (1:1)
    for t in matchable:
        key = t.dedup_key or f"pk{t.pk}"
        if key in used_tx:
            continue
        sugg = primary_by_tx.get(key)
        if not sugg:
            continue
        top = sugg[0]
        if top.item_id in used_item:
            continue
        used_tx.add(key)
        used_item.add(top.item_id)
        direction = item_direction[top.item_id]
        recon.append(
            {
                "id": f"tx:{t.pk}",
                "status": "a_confirmar",
                "direction": direction,
                "kind": None,
                "rule": RULE_LABEL[top.rule],
                "facts": _facts(top.reason),
                "signed_by": None,
                "audit": [],
                "bank": _bank_side(t),
                "doc": _doc_side(item_by_ext[top.item_id]),
                "bank_many": None,
                "doc_many": None,
                "candidates": None,
                "cents": _doc_signed(item_by_ext[top.item_id]),
            }
        )

    # 3. sugestões ambíguas → a confirmar com candidatos
    for t in matchable:
        key = t.dedup_key or f"pk{t.pk}"
        if key in used_tx:
            continue
        sugg = ambiguous_by_tx.get(key)
        if not sugg:
            continue
        used_tx.add(key)
        cands = [item_by_ext[s.item_id] for s in sugg]
        recon.append(
            {
                "id": f"tx:{t.pk}",
                "status": "a_confirmar",
                "direction": item_direction[sugg[0].item_id],
                "kind": None,
                "rule": RULE_LABEL[Rule.AMBIGUOUS],
                "facts": _facts(sugg[0].reason),
                "signed_by": None,
                "audit": [],
                "bank": _bank_side(t),
                "doc": None,
                "bank_many": None,
                "doc_many": None,
                "candidates": [{**_doc_side(c), "note": c.counterpart_name or ""} for c in cands],
                "cents": _doc_signed(cands[0]),
            }
        )

    # 4. N:N → a confirmar
    for g in groups:
        if g.kind == "partial":
            txs_g = [tx_by_key[k] for k in g.transaction_keys]
            it_g = item_by_ext[g.item_ids[0]]
            direction = item_direction[g.item_ids[0]]
            gid = f"grp:p:{it_g.pk}:" + ":".join(str(t.pk) for t in txs_g)
            used_tx.update(t.dedup_key or f"pk{t.pk}" for t in txs_g)
            used_item.add(g.item_ids[0])
            recon.append(
                {
                    "id": gid,
                    "status": "a_confirmar",
                    "direction": direction,
                    "kind": "partial",
                    "rule": RULE_LABEL[Rule.PARTIAL],
                    "facts": _facts(g.reason),
                    "signed_by": None,
                    "audit": [],
                    "bank": None,
                    "doc": _doc_side(it_g),
                    "bank_many": [_bank_side(t) for t in txs_g],
                    "doc_many": None,
                    "candidates": None,
                    "cents": _doc_signed(it_g),
                }
            )
        else:  # batch
            tx_g = tx_by_key[g.transaction_keys[0]]
            its_g = [item_by_ext[i] for i in g.item_ids]
            direction = item_direction[g.item_ids[0]]
            gid = f"grp:b:{tx_g.pk}:" + ":".join(str(i.pk) for i in its_g)
            used_tx.add(tx_g.dedup_key or f"pk{tx_g.pk}")
            used_item.update(g.item_ids)
            recon.append(
                {
                    "id": gid,
                    "status": "a_confirmar",
                    "direction": direction,
                    "kind": "batch",
                    "rule": RULE_LABEL[Rule.BATCH],
                    "facts": _facts(g.reason),
                    "signed_by": None,
                    "audit": [],
                    "bank": _bank_side(tx_g),
                    "doc": None,
                    "bank_many": None,
                    "doc_many": [_doc_side(i) for i in its_g],
                    "candidates": None,
                    "cents": sum(_doc_signed(i) for i in its_g),
                }
            )

    # 5. classificados (despesa/receita sem documento)
    for t in classified:
        used_tx.add(t.dedup_key or f"pk{t.pk}")
        direction = t.classification_direction or ("in" if t.amount_cents > 0 else "out")
        recon.append(
            {
                "id": f"tx:{t.pk}",
                "status": "classificado",
                "direction": direction,
                "kind": None,
                "rule": CLASSIFICATIONS.get(t.classification, {}).get("label"),
                "facts": [t.classified_note] if t.classified_note else [],
                "signed_by": f"classificado por {t.classified_by or 'você'}",
                "audit": [],
                "bank": _bank_side(t),
                "doc": None,
                "bank_many": None,
                "doc_many": None,
                "candidates": None,
                "cents": t.amount_cents,
            }
        )

    # 6. transferências entre contas (neutras)
    for t in transfers:
        used_tx.add(t.dedup_key or f"pk{t.pk}")
        recon.append(
            {
                "id": f"tx:{t.pk}",
                "status": "transferencia",
                "direction": "in" if t.amount_cents > 0 else "out",
                "kind": None,
                "rule": None,
                "facts": [],
                "signed_by": f"vinculado por {t.classified_by or 'você'}",
                "audit": [],
                "bank": _bank_side(t),
                "doc": None,
                "bank_many": None,
                "doc_many": None,
                "candidates": None,
                "cents": 0,
            }
        )

    # 7. lançamentos sem sugestão → só no banco
    for t in matchable:
        key = t.dedup_key or f"pk{t.pk}"
        if key in used_tx:
            continue
        used_tx.add(key)
        recon.append(
            {
                "id": f"tx:{t.pk}",
                "status": "nao_identificado",
                "direction": "in" if t.amount_cents > 0 else "out",
                "kind": None,
                "rule": None,
                "facts": [],
                "signed_by": None,
                "audit": [],
                "bank": _bank_side(t),
                "doc": None,
                "bank_many": None,
                "doc_many": None,
                "candidates": None,
                "cents": t.amount_cents,
            }
        )

    # 8. itens sem vínculo → pendente / atrasado / cancelado
    from django.utils import timezone

    today = timezone.localdate()
    for i in items:
        if i.external_id in used_item:
            continue
        used_item.add(i.external_id)
        sit = classify_item(_to_core_item(i), 0, False, today)
        status = {
            "settled": "conciliado",
            "pending": "pendente",
            "overdue": "atrasado",
            "cancelled": "cancelado",
        }[sit.state.value]
        recon.append(
            {
                "id": f"it:{i.pk}",
                "status": status,
                "direction": DIR[Direction(i.direction)],
                "kind": None,
                "rule": None,
                "facts": [],
                "signed_by": None,
                "audit": [],
                "bank": None,
                "doc": _doc_side(i),
                "bank_many": None,
                "doc_many": None,
                "candidates": None,
                "cents": _doc_signed(i),
            }
        )

    recon.sort(key=lambda r: ORDER.index(r["status"]) if r["status"] in ORDER else 99)

    balance = _balance(
        txns,
        links,
        classified,
        opening_cents=(
            period.opening_balance_cents
            if period is not None
            else (account.opening_balance_cents if account else None)
        ),
        statement_closing_cents=_statement_closing(account, period),
    )
    totals = _totals(recon)
    counts = {
        "a_confirmar": sum(1 for r in recon if r["status"] == "a_confirmar"),
        "a_confirmar_lote": sum(
            1 for r in recon if r["status"] == "a_confirmar" and not r.get("candidates")
        ),
    }
    return {
        "items": recon,
        "totals": totals,
        "balance": balance,
        "counts": counts,
        "filtros": _filtros(recon),
        "filtro": "todos",
    }


def _statement_closing(
    account: models.BankAccount | None, period: models.Period | None
) -> int | None:
    """Saldo final do extrato **do período**.

    O ``LEDGERBAL`` do arquivo é o saldo final do extrato inteiro: só serve para o período
    quando o período alcança o último lançamento importado. Para um mês passado, o saldo do
    banco é o que foi gravado no fechamento — nunca o saldo de hoje.
    """
    if account is None:
        return None
    if period is None:
        return account.ledger_balance_cents
    if period.closing_balance_cents is not None:
        return period.closing_balance_cents
    last = models.BankTransaction.objects.filter(account=account).aggregate(last=Max("posted_on"))[
        "last"
    ]
    if last is None or last <= period.end:
        return account.ledger_balance_cents
    return None


def _balance(
    txns: list[models.BankTransaction],
    links: list[models.Link],
    classified: list[models.BankTransaction],
    opening_cents: int | None,
    statement_closing_cents: int | None,
) -> dict:
    """Conciliação bancária de saldo: extrato × razão derivada dos documentos."""
    statement_inflows = sum(t.amount_cents for t in txns if t.amount_cents > 0)
    statement_outflows = -sum(t.amount_cents for t in txns if t.amount_cents < 0)

    # razão: baixas (pelo valor do documento) + classificados (pelo valor do extrato)
    ledger_lines: list[LedgerLine] = []
    value_gap_cents = 0
    n_value_gap = 0
    for group in _connected_links(links):
        txns_g = {ln.transaction for ln in group}
        items_g = {ln.item for ln in group}
        bank_signed = sum(t.amount_cents for t in txns_g)
        doc_signed = sum(_doc_signed(i) for i in items_g)
        gap = doc_signed - bank_signed
        value_gap_cents += gap
        if gap != 0:
            n_value_gap += 1
        for i in items_g:
            ledger_lines.append(
                LedgerLine(f"lk:{group[0].pk}", Direction(i.direction), i.amount_cents, "settled")
            )
    classified_lines = 0
    for t in classified:
        d = Direction(t.classification_direction or ("inflow" if t.amount_cents > 0 else "outflow"))
        ledger_lines.append(LedgerLine(f"tx:{t.pk}", d, abs(t.amount_cents), "classified"))
        classified_lines += 1

    # o que ainda não tem explicação = lançamentos sem vínculo e sem classificação
    explained_pks = (
        {ln.transaction_id for ln in links}
        | {t.pk for t in classified}
        | {t.pk for t in txns if t.classification == "transferencia"}
    )
    unexplained_cents = sum(t.amount_cents for t in txns if t.pk not in explained_pks)
    n_unexplained = sum(1 for t in txns if t.pk not in explained_pks)

    res = reconcile_balances(
        opening_cents=opening_cents,
        statement_inflows=statement_inflows,
        statement_outflows=statement_outflows,
        statement_closing_cents=statement_closing_cents,
        ledger_lines=ledger_lines,
        value_gap_cents=value_gap_cents,
        unexplained_cents=unexplained_cents,
    )

    settled_in = 0
    settled_out = 0
    for group in _connected_links(links):
        for i in {ln.item for ln in group}:
            if i.direction == "inflow":
                settled_in += i.amount_cents
            else:
                settled_out += i.amount_cents
    class_in = sum(t.amount_cents for t in classified if t.amount_cents > 0)
    class_out = -sum(t.amount_cents for t in classified if t.amount_cents < 0)

    return {
        "opening": res.opening_cents,
        "statement_inflows": res.statement_inflows,
        "statement_outflows": res.statement_outflows,
        "statement_closing": res.statement_closing_cents,
        "statement_consistent": res.statement_consistent,
        "settled_in": settled_in,
        "settled_out": settled_out,
        "classified_in": class_in,
        "classified_out": class_out,
        "ledger_inflows": res.ledger_inflows,
        "ledger_outflows": res.ledger_outflows,
        "ledger_closing": res.ledger_closing_cents,
        "difference": res.difference_cents,
        "unexplained": unexplained_cents,
        "value_gap": value_gap_cents,
        "balanced": res.balanced,
        "consistent": res.consistent,
        "n_unexplained": n_unexplained,
        "n_value_gap": n_value_gap,
        "n_classified": classified_lines,
    }


def _totals(recon: list[dict]) -> dict:
    def ssum(pred) -> int:
        return sum(abs(r["cents"]) for r in recon if pred(r))

    def cnt(pred) -> int:
        return sum(1 for r in recon if pred(r))

    def settled(r: dict) -> bool:
        return r["status"] in ("conciliado", "divergencia")

    totals = {
        "recebido": ssum(lambda r: settled(r) and r["direction"] == "in"),
        "n_recebido": cnt(lambda r: settled(r) and r["direction"] == "in"),
        "a_receber": ssum(lambda r: r["status"] == "pendente" and r["direction"] == "in"),
        "n_a_receber": cnt(lambda r: r["status"] == "pendente" and r["direction"] == "in"),
        "atrasado": ssum(lambda r: r["status"] == "atrasado"),
        "n_atrasado": cnt(lambda r: r["status"] == "atrasado"),
        "pago": ssum(lambda r: settled(r) and r["direction"] == "out"),
        "n_pago": cnt(lambda r: settled(r) and r["direction"] == "out"),
        "a_pagar": ssum(lambda r: r["status"] == "pendente" and r["direction"] == "out"),
        "n_a_pagar": cnt(lambda r: r["status"] == "pendente" and r["direction"] == "out"),
        "nao_identificado": ssum(lambda r: r["status"] == "nao_identificado"),
        "n_nid": cnt(lambda r: r["status"] == "nao_identificado"),
    }
    for key in ("n_recebido", "n_a_receber", "n_atrasado", "n_pago", "n_a_pagar", "n_nid"):
        n = totals[key]
        totals[f"{key}_txt"] = f"{n} lançamento{'s' if n != 1 else ''}"
    return totals


def _filtros(recon: list[dict]) -> list[dict]:
    labels = [
        ("todos", "Todos"),
        ("a_confirmar", "Para confirmar"),
        ("conciliado", "Recebido e pago"),
        ("pendente", "Pendente"),
        ("atrasado", "Atrasado"),
        ("nao_identificado", "Não identificado"),
        ("divergencia", "Com diferença"),
        ("classificado", "Classificado"),
        ("transferencia", "Transferências"),
    ]
    out = []
    for sid, label in labels:
        count = len(recon) if sid == "todos" else sum(1 for r in recon if r["status"] == sid)
        out.append({"id": sid, "label": label, "count": count})
    return out
