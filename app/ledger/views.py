"""Views do conciliador (Plano 2) — renderizadas no servidor + HTMX.

As telas leem dados reais do banco, conciliados pelo motor (``services.reconcile``).
Mutações (confirmar/recusar/desfazer) gravam vínculos e respondem com ``HX-Redirect``.
"""

from __future__ import annotations

from accounts.models import Role
from accounts.views import resolve_company
from conciliador_ui.landing_context import landing_context
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render

from . import models, services

_RULE_KEY = {
    "Regra 1": "document",
    "Regra 2": "number",
    "Regra 3": "unique",
    "Parcela": "partial",
    "Remessa": "batch",
    "Manual": "manual",
}


def _company_of(request: HttpRequest) -> models.Company:
    company, _role = resolve_company(request)
    if company is None:
        raise PermissionError("usuário sem empresa")
    return company


def _role_of(request: HttpRequest) -> str | None:
    return resolve_company(request)[1]


def _who(request: HttpRequest) -> str:
    return request.user.get_full_name() or request.user.email


def _dono_required(view_func):
    """Só o dono muta; o contador é somente leitura (403 se tentar via POST direto)."""
    from functools import wraps

    @wraps(view_func)
    def _wrapped(request: HttpRequest, *args, **kwargs):
        if _role_of(request) == Role.ACCOUNTANT:
            return HttpResponse(status=403)
        return view_func(request, *args, **kwargs)

    return _wrapped


def _conta(
    request: HttpRequest, company: models.Company
) -> tuple[models.BankAccount | None, list[models.BankAccount]]:
    """Conta selecionada em ``?conta=<pk>`` (padrão: a primeira da empresa)."""
    contas = list(models.BankAccount.objects.filter(company=company).order_by("-is_primary", "pk"))
    raw = request.GET.get("conta")
    for c in contas:
        if str(c.pk) == raw:
            return c, contas
    return (contas[0] if contas else None), contas


def _periodo(conta: models.BankAccount | None) -> dict:
    from django.db.models import Max, Min

    if conta is None:
        return {"slug": "atual", "label": "Período atual", "start": None, "end": None}
    agg = models.BankTransaction.objects.filter(account=conta).aggregate(
        first=Min("posted_on"), last=Max("posted_on")
    )
    return {"slug": "atual", "label": "Período atual", "start": agg["first"], "end": agg["last"]}


def _base(request: HttpRequest, nav: str) -> tuple[dict, models.Company]:
    company = _company_of(request)
    view = "contador" if _role_of(request) == Role.ACCOUNTANT else "dono"
    conta, contas = _conta(request, company)
    ctx = services.reconcile(company, conta)
    periodo = _periodo(conta)
    ctx.update(
        {
            "org": {"name": company.name, "cnpj": company.cnpj},
            "conta": {"id": conta.pk, "label": conta.label} if conta else None,
            "contas": [{"id": c.pk, "label": c.label} for c in contas],
            "periodo": periodo,
            "periodos": [periodo],
            "view": view,
            "nav": nav,
            "conta_id": conta.pk if conta else None,
            "qs_conta": f"&conta={conta.pk}" if conta else "",
            "conta_empresa_id": company.pk,
            "empresas": [
                {"company_id": m.company_id, "company_name": m.company.name}
                for m in request.user.memberships.select_related("company").order_by(
                    "company__name"
                )
            ],
        }
    )
    return ctx, company


def _back(conta_id: int | None) -> str:
    return "/fechamento/atual/" + (f"?conta={conta_id}" if conta_id else "")


def _filtered(items: list[dict], filtro: str) -> list[dict]:
    if filtro == "todos":
        return items
    return [i for i in items if i["status"] == filtro]


def _filtros_contador(recon: list[dict]) -> list[dict]:
    mapa = [
        ("todos", "Todos", None),
        ("conciliado", "Conciliado", ["conciliado"]),
        ("banco", "Só no banco", ["nao_identificado"]),
        ("aberto", "Só nos documentos · em aberto", ["pendente"]),
        ("vencido", "Só nos documentos · vencido", ["atrasado"]),
        ("divergencia", "Divergência", ["divergencia"]),
        ("classificado", "Só no banco · classificado", ["classificado"]),
        ("transferencia", "Transferências entre contas", ["transferencia"]),
        ("a_confirmar", "Sugestões não confirmadas", ["a_confirmar"]),
    ]
    out = []
    for sid, label, statuses in mapa:
        count = len(recon) if sid == "todos" else sum(1 for r in recon if r["status"] in statuses)
        out.append({"id": sid, "label": label, "count": count})
    return out


@login_required
def fechamento(request: HttpRequest, periodo_slug: str):
    ctx, _ = _base(request, "fechamento")
    filtro = request.GET.get("f", "todos")
    ctx["filtro"] = filtro
    if ctx["view"] == "contador":
        ctx["filtros"] = _filtros_contador(ctx["items"])
        ctx["items"] = _filtered_contador(ctx["items"], filtro)
        return render(request, "app/demonstrativo.html", ctx)
    ctx["items"] = _filtered(ctx["items"], filtro)
    return render(request, "app/fechamento.html", ctx)


def _filtered_contador(items: list[dict], filtro: str) -> list[dict]:
    mapa = {
        "conciliado": ["conciliado"],
        "banco": ["nao_identificado"],
        "aberto": ["pendente"],
        "vencido": ["atrasado"],
        "divergencia": ["divergencia"],
        "classificado": ["classificado"],
        "transferencia": ["transferencia"],
        "a_confirmar": ["a_confirmar"],
    }
    if filtro in mapa:
        return [i for i in items if i["status"] in mapa[filtro]]
    return items


@login_required
def fechamento_totais(request: HttpRequest, periodo_slug: str):
    ctx, _ = _base(request, "fechamento")
    return render(request, "app/_totais.html", ctx)


@login_required
def fechamento_lista(request: HttpRequest, periodo_slug: str):
    ctx, _ = _base(request, "fechamento")
    filtro = request.GET.get("f", "todos")
    ctx["filtro"] = filtro
    ctx["items"] = _filtered(ctx["items"], filtro)
    template = "app/_lista.html" if request.headers.get("HX-Request") else "app/fechamento.html"
    return render(request, template, ctx)


def _find_item(company: models.Company, item_id: str) -> dict | None:
    """Procura o item em todas as contas (o id traz o prefixo ``tx:``/``it:``/``lk:``)."""
    for it in services.reconcile(company)["items"]:
        if it["id"] == item_id:
            return it
    return None


@login_required
def item_detalhe(request: HttpRequest, item_id: str):
    ctx, company = _base(request, "fechamento")
    item = _find_item(company, item_id)
    if not item:
        return redirect("fechamento", "atual")
    doc = item["doc"] or (item["candidates"][0] if item["candidates"] else None)
    conta_id = item["bank"]["account_id"] if item.get("bank") else None
    ctx.update(
        {
            "item": item,
            "doc_exibido": doc,
            "titulo": (item["bank"] or {}).get("memo")
            or (doc or {}).get("counterpart")
            or "Vínculo",
            "classificacoes": _classificacoes_para(item),
            "transferencias": _transferencias_para(company, item, conta_id),
            "lancamentos_livres": [
                {
                    "id": i["bank"]["id"],
                    "date": i["bank"]["date"],
                    "memo": i["bank"]["memo"],
                    "cents": i["bank"]["cents"],
                }
                for i in services.reconcile(company, _conta_by_id(company, conta_id))["items"]
                if i["status"] == "nao_identificado" and i.get("bank")
            ],
        }
    )
    return render(request, "app/detalhe.html", ctx)


def _classificacoes_para(item: dict) -> list[dict]:
    """Classificações possíveis para um lançamento "só no banco", já filtradas pela direção."""
    out = []
    for key, meta in services.CLASSIFICATIONS.items():
        d = meta["direction"]
        if key == "transferencia":
            out.append({"key": key, "label": meta["label"], "direction": ""})
            continue
        if key == "outro":
            out.append({"key": key, "label": meta["label"], "direction": item["direction"]})
            continue
        out.append({"key": key, "label": meta["label"], "direction": d})
    return out


def _transferencias_para(company: models.Company, item: dict, conta_id: int | None) -> list[dict]:
    """Lançamentos de outras contas com sinal oposto e valor próximo (transferência)."""
    if not item.get("bank") or conta_id is None:
        return []
    t = models.BankTransaction.objects.get(pk=item["bank"]["id"])
    qs = models.BankTransaction.objects.filter(account__company=company).exclude(
        account_id=conta_id
    )
    if t.amount_cents > 0:
        qs = qs.filter(amount_cents__lt=0, amount_cents__gte=-t.amount_cents - 100).filter(
            amount_cents__lte=-t.amount_cents + 100
        )
    else:
        qs = qs.filter(amount_cents__gt=0, amount_cents__lte=-t.amount_cents + 100).filter(
            amount_cents__gte=-t.amount_cents - 100
        )
    out = []
    for o in qs.select_related("account").order_by("-posted_on")[:20]:
        out.append(
            {
                "id": o.pk,
                "date": o.posted_on,
                "memo": o.memo,
                "cents": o.amount_cents,
                "account": o.account.label,
            }
        )
    return out


def _conta_by_id(company: models.Company, conta_id: int | None) -> models.BankAccount | None:
    if conta_id is None:
        return None
    return models.BankAccount.objects.filter(company=company, pk=conta_id).first()


def _create_links(company: models.Company, pairs: list[tuple], rule: str, who: str = "") -> None:
    for tx, it in pairs:
        models.Link.objects.update_or_create(
            company=company,
            transaction=tx,
            item=it,
            defaults={"rule": rule, "created_by": who},
        )


def _confirm(
    company: models.Company, item: dict, doc_id: int | None = None, who: str = ""
) -> int | None:
    """Cria os vínculos de uma sugestão (1:1, ambígua, parcela ou remessa). Devolve a conta."""
    if item["id"].startswith("grp:"):
        _, kind, anchor, *rest = item["id"].split(":")
        if kind == "p":
            it = models.ExpectedItem.objects.get(pk=int(anchor))
            txns = list(models.BankTransaction.objects.filter(pk__in=[int(x) for x in rest]))
            _create_links(company, [(t, it) for t in txns], "partial", who)
            return txns[0].account_id
        tx = models.BankTransaction.objects.get(pk=int(anchor))
        its = list(models.ExpectedItem.objects.filter(pk__in=[int(x) for x in rest]))
        _create_links(company, [(tx, i) for i in its], "batch", who)
        return tx.account_id

    tx = models.BankTransaction.objects.get(pk=item["bank"]["id"])
    if item.get("candidates"):
        doc_id = doc_id or item["candidates"][0]["id"]
    else:
        doc_id = item["doc"]["id"]
    it = models.ExpectedItem.objects.get(pk=doc_id)
    _create_links(company, [(tx, it)], _RULE_KEY.get(item.get("rule"), "unique"), who)
    return tx.account_id


@login_required
@_dono_required
def item_confirmar(request: HttpRequest, item_id: str):
    company = _company_of(request)
    item = _find_item(company, item_id)
    if not item:
        return HttpResponse(status=404)
    conta_id = _confirm(company, item, request.POST.get("doc_id"), _who(request))
    return HttpResponse(headers={"HX-Redirect": _back(conta_id)})


@login_required
@_dono_required
def item_recusar(request: HttpRequest, item_id: str):
    company = _company_of(request)
    item = _find_item(company, item_id)
    if not item or item.get("kind"):
        return HttpResponse(status=404)
    tx = models.BankTransaction.objects.get(pk=item["bank"]["id"])
    doc_id = item["doc"]["id"] if item.get("doc") else item["candidates"][0]["id"]
    it = models.ExpectedItem.objects.get(pk=doc_id)
    models.RejectedLink.objects.get_or_create(company=company, transaction=tx, item=it)
    return HttpResponse(headers={"HX-Redirect": _back(tx.account_id)})


@login_required
@_dono_required
def item_desfazer(request: HttpRequest, item_id: str):
    if not item_id.startswith("lk:"):
        return HttpResponse(status=404)
    try:
        link = models.Link.objects.select_related("transaction").get(pk=int(item_id[3:]))
    except (ValueError, models.Link.DoesNotExist):
        return HttpResponse(status=404)
    conta_id = services.unlink_group(link)
    return HttpResponse(headers={"HX-Redirect": _back(conta_id)})


@login_required
@_dono_required
def item_classificar(request: HttpRequest, item_id: str):
    company = _company_of(request)
    item = _find_item(company, item_id)
    if not item or not item.get("bank"):
        return HttpResponse(status=404)
    tx = models.BankTransaction.objects.get(pk=item["bank"]["id"])
    kind = request.POST.get("kind", "outro")
    meta = services.CLASSIFICATIONS.get(kind, services.CLASSIFICATIONS["outro"])
    if kind == "transferencia":
        tx.classification = "transferencia"
        tx.classification_direction = ""
        counter = request.POST.get("counterpart") or ""
        tx.transfer_counterpart_id = int(counter) if counter else None
    else:
        direction = meta["direction"] or request.POST.get("direction", "out")
        tx.classification = kind
        tx.classification_direction = "inflow" if direction == "in" else "outflow"
        tx.transfer_counterpart = None
    tx.classified_note = (request.POST.get("note") or "")[:200]
    tx.classified_by = _who(request)
    from django.utils import timezone

    tx.classified_at = timezone.now()
    tx.save()
    return HttpResponse(headers={"HX-Redirect": _back(tx.account_id)})


@login_required
@_dono_required
def item_desclassificar(request: HttpRequest, item_id: str):
    item = _find_item(_company_of(request), item_id)
    if not item or not item.get("bank"):
        return HttpResponse(status=404)
    tx = models.BankTransaction.objects.get(pk=item["bank"]["id"])
    tx.classification = ""
    tx.classification_direction = ""
    tx.classified_note = ""
    tx.transfer_counterpart = None
    tx.save(
        update_fields=[
            "classification",
            "classification_direction",
            "classified_note",
            "transfer_counterpart",
        ]
    )
    return HttpResponse(headers={"HX-Redirect": _back(tx.account_id)})


@login_required
@_dono_required
def aprovar_lote(request: HttpRequest):
    """Confirma de uma vez todas as sugestões de alta confiança (sem candidatos empatados)."""
    company = _company_of(request)
    conta, _ = _conta(request, company)
    ctx = services.reconcile(company, conta)
    who = _who(request)
    for item in ctx["items"]:
        if item["status"] != "a_confirmar" or item.get("candidates"):
            continue
        _confirm(company, item, who=who)
    return HttpResponse(headers={"HX-Redirect": _back(conta.pk if conta else None)})


@login_required
def importacao(request: HttpRequest):
    base, _ = _base(request, "importacao")
    base.update(
        {
            "fontes": _fontes(),
            "jobs": {k: {"state": "idle"} for k in ("ofx", "nfe", "nfse", "csv")},
            "importacoes": [],
            "duplicatas": [],
        }
    )
    return render(request, "app/importacao.html", base)


def landing(request: HttpRequest):
    return render(request, "site/landing.html", landing_context())


def health(request: HttpRequest):
    """Sonda de saúde (usada pelo processo local e, depois, pelo deploy)."""
    return JsonResponse({"status": "ok"})


# --------------------------------------------------------------------------- #
# Stubs do MVP (exportações, upload real, convites de contador) — ligados depois.
# --------------------------------------------------------------------------- #
@login_required
def demonstrativo_lista(request: HttpRequest, periodo_slug: str):
    ctx, _ = _base(request, "fechamento")
    filtro = request.GET.get("f", "todos")
    ctx["filtros"] = _filtros_contador(ctx["items"])
    ctx["items"] = _filtered_contador(ctx["items"], filtro)
    return render(request, "app/demonstrativo.html", ctx)


@login_required
def demonstrativo_csv(request: HttpRequest, periodo_slug: str):
    return HttpResponse("demonstrativo.csv (placeholder)\n", content_type="text/csv")


@login_required
def demonstrativo_pdf(request: HttpRequest, periodo_slug: str):
    return HttpResponse("demonstrativo.pdf (placeholder)", content_type="text/plain")


@login_required
@_dono_required
def vinculo_manual(request: HttpRequest):
    """Vincula manualmente um documento a um lançamento (parcial ou quitado com diferença)."""
    company = _company_of(request)
    it = models.ExpectedItem.objects.get(pk=request.POST["doc_id"])
    tx = models.BankTransaction.objects.get(pk=request.POST["bank_id"])
    mode = request.POST.get("mode", "parcial")
    reason = request.POST.get("reason", "")
    with_difference = mode == "quitar" and abs(tx.amount_cents) != it.amount_cents
    models.Link.objects.update_or_create(
        company=company,
        transaction=tx,
        item=it,
        defaults={
            "rule": "manual",
            "closed_with_difference": with_difference,
            "reason": reason,
            "created_by": _who(request),
        },
    )
    return HttpResponse(headers={"HX-Redirect": _back(tx.account_id)})


@login_required
def importacao_enviar(request: HttpRequest, kind: str):
    return render(
        request,
        "ds/dropzone.html",
        {
            "source": _fontes()[kind],
            "job": {"state": "done", "file_name": "enviado", "result": "processado"},
        },
    )


@login_required
def importacao_duplicatas(request: HttpRequest):
    return render(request, "app/_duplicatas.html", {"duplicatas": []})


@login_required
def modelo_csv(request: HttpRequest):
    from conciliador_core import template_csv

    return HttpResponse(template_csv, content_type="text/csv")


@login_required
def duplicatas_revisar(request: HttpRequest):
    return redirect("fechamento", "atual")


def _fontes() -> dict:
    return {
        "ofx": {
            "kind": "ofx",
            "title": "Extrato bancário",
            "formats": ".ofx",
            "accept": ".ofx",
            "description": "Exporte no internet banking, em OFX. Repetidos são ignorados.",
        },
        "nfe": {
            "kind": "nfe",
            "title": "NF-e",
            "formats": ".xml · modelo 55",
            "accept": ".xml",
            "description": "Notas emitidas viram a receber; recebidas de fornecedores, a pagar.",
        },
        "nfse": {
            "kind": "nfse",
            "title": "NFS-e",
            "formats": ".xml · padrão nacional",
            "accept": ".xml",
            "description": (
                "Sem vencimento na nota, usamos emissão + 30 dias. Você pode mudar item a item."
            ),
        },
        "csv": {
            "kind": "csv",
            "title": "Contas a pagar e a receber",
            "formats": ".csv",
            "accept": ".csv",
            "description": "Aluguel, salários, contratos sem nota. Use o nosso modelo.",
        },
    }
