"""Autenticação, MFA (TOTP), convite de contador e troca de empresa."""

from __future__ import annotations

import json

import pyotp
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect, render, resolve_url
from django.utils import timezone
from ledger.audit import log as audit_log
from ledger.models import Company

from . import ratelimit
from .cnpj import CnpjCheck, check_cnpj
from .models import Invite, Membership, Role, User


def _redirect(request: HttpRequest, to: str, *args: object, **kwargs: object) -> HttpResponse:
    """Redireciona; sob hx-boost responde 200 + HX-Redirect para o HTMX navegar de fato."""
    if request.headers.get("HX-Request"):
        response = HttpResponse(status=200)
        response["HX-Redirect"] = resolve_url(to, *args, **kwargs)
        return response
    return redirect(to, *args, **kwargs)


def resolve_company(request: HttpRequest) -> tuple[Company | None, str | None]:
    """Empresa e papel ativos do usuário (padrão: a primeira membresia)."""
    user = request.user
    if not user.is_authenticated:
        return None, None
    memberships = list(user.memberships.select_related("company").order_by("company__name"))
    if not memberships:
        return None, None
    wanted = request.GET.get("empresa") or request.session.get("active_company_id")
    chosen = (
        next((m for m in memberships if str(m.company_id) == str(wanted)), None) or memberships[0]
    )
    request.session["active_company_id"] = chosen.company_id
    return chosen.company, chosen.role


def _role_view(role: str | None) -> str:
    return "contador" if role == Role.ACCOUNTANT else "dono"


def _active_memberships(user: User) -> list[Membership]:
    return list(user.memberships.select_related("company").order_by("company__name"))


def signup(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        ip = ratelimit.client_ip(request)
        if ratelimit.blocked("signup-ip", ip, ratelimit.SIGNUP_LIMIT):
            return render(
                request,
                "accounts/signup.html",
                {"error": "Muitas contas criadas deste endereço. Tente mais tarde."},
                status=429,
            )
        email = (request.POST.get("email") or "").strip().lower()
        name = (request.POST.get("name") or "").strip()
        password = request.POST.get("password") or ""
        if not email or not name or len(password) < 8:
            return render(
                request,
                "accounts/signup.html",
                {
                    "error": "Preencha nome, e-mail e uma senha de pelo menos 8 caracteres.",
                    "email": email,
                    "name": name,
                },
                status=400,
            )
        if User.objects.filter(email=email).exists():
            return render(
                request,
                "accounts/signup.html",
                {"error": "Já existe uma conta com este e-mail.", "email": email, "name": name},
                status=400,
            )
        user = User.objects.create_user(email, name, password)
        ratelimit.hit("signup-ip", ip, ratelimit.SIGNUP_WINDOW)
        company = Company.objects.create(name=f"Empresa de {name}", cnpj=_placeholder_cnpj(user))
        Membership.objects.create(user=user, company=company, role=Role.OWNER)
        login(request, user)
        request.session["active_company_id"] = company.pk
        audit_log(request, "signup", company=company, target=email)
        # convite de contador pendente (o link veio antes do cadastro)
        token = request.session.get("pending_invite_token")
        if token:
            invite = (
                Invite.objects.select_related("company").filter(token=token, accepted=False).first()
            )
            if invite is not None:
                Membership.objects.get_or_create(
                    user=user, company=invite.company, defaults={"role": Role.ACCOUNTANT}
                )
                invite.accepted = True
                invite.save(update_fields=["accepted"])
                request.session["active_company_id"] = invite.company_id
                audit_log(request, "invite_accepted", company=invite.company, target=email)
            request.session.pop("pending_invite_token", None)
        return _redirect(request, "fechamento", "atual")
    return render(request, "accounts/signup.html")


def _placeholder_cnpj(user: User) -> str:
    # CNPJ provisório derivado do id (só até a pessoa informar o real em "Empresa").
    return f"00{user.pk:012d}"[:14]


def login_view(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        password = request.POST.get("password") or ""
        ip = ratelimit.client_ip(request)
        if ratelimit.blocked("login-email", email, ratelimit.LOGIN_LIMIT) or ratelimit.blocked(
            "login-ip", ip, ratelimit.LOGIN_IP_LIMIT
        ):
            audit_log(request, "login_blocked", actor_email=email)
            return render(
                request,
                "accounts/login.html",
                {
                    "error": "Muitas tentativas de acesso. Aguarde 15 minutos e tente de novo.",
                    "email": email,
                },
                status=429,
            )
        user = authenticate(request, username=email, password=password)
        if user is None:
            ratelimit.hit("login-email", email, ratelimit.LOGIN_WINDOW)
            ratelimit.hit("login-ip", ip, ratelimit.LOGIN_WINDOW)
            audit_log(request, "login_failed", actor_email=email)
            return render(
                request,
                "accounts/login.html",
                {"error": "E-mail ou senha incorretos.", "email": email},
            )
        ratelimit.clear("login-email", email)
        if user.mfa_secret:
            request.session["mfa_pending_user_id"] = user.pk
            audit_log(request, "login_first_factor_ok", actor_email=email)
            return _redirect(request, "mfa_verify")
        login(request, user)
        audit_log(request, "login_ok", actor_email=email)
        return _redirect(request, "fechamento", "atual")
    return render(request, "accounts/login.html")


def mfa_verify(request: HttpRequest) -> HttpResponse:
    user_id = request.session.get("mfa_pending_user_id")
    user = User.objects.filter(pk=user_id).first() if user_id else None
    if user is None:
        return _redirect(request, "login")
    ip = ratelimit.client_ip(request)
    if request.method == "POST":
        if ratelimit.blocked("mfa", f"{user.pk}:{ip}", ratelimit.MFA_LIMIT):
            audit_log(request, "mfa_blocked", actor_email=user.email)
            return render(
                request,
                "accounts/mfa.html",
                {"error": "Muitos códigos errados. Aguarde 5 minutos e tente de novo."},
                status=429,
            )
        code = (request.POST.get("code") or "").strip()
        if pyotp.TOTP(user.mfa_secret).verify(code):
            ratelimit.clear("mfa", f"{user.pk}:{ip}")
            login(request, user)
            request.session.pop("mfa_pending_user_id", None)
            audit_log(request, "login_ok", actor_email=user.email)
            return _redirect(request, "fechamento", "atual")
        ratelimit.hit("mfa", f"{user.pk}:{ip}", ratelimit.MFA_WINDOW)
        audit_log(request, "mfa_failed", actor_email=user.email)
        return render(request, "accounts/mfa.html", {"error": "Código inválido."})
    return render(request, "accounts/mfa.html")


def logout_view(request: HttpRequest) -> HttpResponseRedirect:
    if request.user.is_authenticated:
        audit_log(request, "logout")
    logout(request)
    return redirect("login")


@login_required
def mfa_setup(request: HttpRequest) -> HttpResponse:
    """Ativa/confirma o MFA (TOTP). O segredo fica na sessão até o código ser confirmado.

    O MFA é obrigatório: não há ação de desativar. O usuário pode trocar de aparelho
    gerando um segredo novo e confirmando o código.
    """
    user: User = request.user
    if request.method == "POST" and request.POST.get("action") == "start":
        request.session["mfa_pending_secret"] = pyotp.random_base32()
    pending = request.session.get("mfa_pending_secret")
    if request.method == "POST" and request.POST.get("action") == "confirm" and pending:
        code = (request.POST.get("code") or "").strip()
        if pyotp.TOTP(pending).verify(code):
            user.mfa_secret = pending
            user.save(update_fields=["mfa_secret"])
            request.session.pop("mfa_pending_secret", None)
            audit_log(request, "mfa_enabled")
            return redirect("mfa_setup")
        return render(
            request,
            "accounts/mfa_setup.html",
            {"error": "Código inválido.", "pending": pending, "otpauth": _otpauth(user, pending)},
            status=400,
        )
    if request.method == "POST" and request.POST.get("action") == "disable":
        return HttpResponse(status=403)
    if request.method == "POST" and request.POST.get("action") == "cancel":
        request.session.pop("mfa_pending_secret", None)
        return redirect("mfa_setup")
    return render(
        request,
        "accounts/mfa_setup.html",
        {"pending": pending, "otpauth": _otpauth(user, pending) if pending else ""},
    )


def _otpauth(user: User, secret: str) -> str:
    label = user.email
    return pyotp.TOTP(secret).provisioning_uri(name=label, issuer_name="conciliador")


def _empresa_error(
    request: HttpRequest, company: Company | None, message: str, new_company: bool
) -> HttpResponse:
    return render(
        request,
        "accounts/empresa.html",
        {"error": message, "company": company, "new_company": new_company},
        status=400,
    )


def _validate_empresa_form(
    request: HttpRequest, company: Company | None, new_company: bool
) -> tuple[str | None, CnpjCheck | None, HttpResponse | None]:
    """Valida nome e CNPJ; devolve ``(nome, check, resposta_de_erro)``."""
    name = (request.POST.get("name") or "").strip()
    cnpj = (request.POST.get("cnpj") or "").strip()
    if not name:
        return (
            None,
            None,
            _empresa_error(request, company, "Informe o nome da empresa.", new_company),
        )
    check = check_cnpj(cnpj)
    if not check.valid_dv:
        return None, None, _empresa_error(request, company, check.error, new_company)
    if check.found is False:
        return None, None, _empresa_error(request, company, check.error, new_company)
    if check.found is True and not check.active:
        return (
            None,
            None,
            _empresa_error(
                request,
                company,
                f"CNPJ com situação {check.situacao}. Só aceitamos CNPJ ativo.",
                new_company,
            ),
        )
    return name, check, None


def _apply_company_fields(company: Company, name: str, check: CnpjCheck) -> None:
    company.name = name
    company.cnpj = check.cnpj
    company.cnpj_verified = check.found is True
    company.cnpj_verified_at = timezone.now() if check.found is True else None
    company.cnpj_status = check.situacao or ""


def _criar_empresa(request: HttpRequest) -> HttpResponse:
    """Cadastra a primeira empresa do usuário (deploy vazio, inclusive superusuário)."""
    if request.method == "POST":
        name, check, error = _validate_empresa_form(request, None, new_company=True)
        if error is not None:
            return error
        if name is None or check is None:  # já validado acima; só para o tipo
            return HttpResponse(status=400)
        company = Company(name=name, cnpj=check.cnpj)
        _apply_company_fields(company, name, check)
        try:
            with transaction.atomic():
                company.save()
                Membership.objects.create(user=request.user, company=company, role=Role.OWNER)
        except IntegrityError:
            return _empresa_error(
                request,
                None,
                "Este CNPJ já está cadastrado em outra empresa.",
                new_company=True,
            )
        request.session["active_company_id"] = company.pk
        audit_log(
            request,
            "company_created",
            company=company,
            target=company.cnpj,
            detail="verificado" if check.found is True else "pendente",
        )
        if check.found is None:
            return render(
                request,
                "accounts/empresa.html",
                {"warning": check.error, "company": company, "saved": True},
            )
        return redirect("fechamento", "atual")
    return render(request, "accounts/empresa.html", {"company": None, "new_company": True})


@login_required
def empresa(request: HttpRequest) -> HttpResponse:
    """O dono informa o CNPJ real; valida o dígito e consulta a Receita."""
    company, role = resolve_company(request)
    if company is None:
        return _criar_empresa(request)
    if role != Role.OWNER:
        return HttpResponse(status=403)
    if request.method == "POST":
        name, check, error = _validate_empresa_form(request, company, new_company=False)
        if error is not None:
            return error
        if name is None or check is None:  # já validado acima; só para o tipo
            return HttpResponse(status=400)
        _apply_company_fields(company, name, check)
        try:
            with transaction.atomic():
                company.save()
        except IntegrityError:
            return _empresa_error(
                request,
                company,
                "Este CNPJ já está cadastrado em outra empresa.",
                new_company=False,
            )
        audit_log(
            request,
            "company_updated",
            company=company,
            target=company.cnpj,
            detail="verificado" if check.found is True else "pendente",
        )
        if check.found is None:
            return render(
                request,
                "accounts/empresa.html",
                {"warning": check.error, "company": company, "saved": True},
            )
        return redirect("fechamento", "atual")
    return render(request, "accounts/empresa.html", {"company": company})


@login_required
def convites(request: HttpRequest) -> HttpResponse:
    company, role = resolve_company(request)
    if role != Role.OWNER:
        return HttpResponse(status=403)
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        invite = Invite.objects.create(
            company=company, email=email, created_by=request.user, token=Invite.new_token()
        )
        audit_log(request, "invite_created", company=company, target=invite.email)
        return redirect("convites")
    invites = list(company.invites.filter(accepted=False).order_by("-created_at"))
    return render(request, "accounts/convites.html", {"invites": invites, "company": company})


def invite_accept(request: HttpRequest, token: str) -> HttpResponse:
    invite = Invite.objects.select_related("company").filter(token=token, accepted=False).first()
    if invite is None:
        return render(
            request, "accounts/invite.html", {"error": "Convite inválido ou já usado."}, status=404
        )
    if not request.user.is_authenticated:
        request.session["pending_invite_token"] = token
        return redirect("signup")
    Membership.objects.get_or_create(
        user=request.user, company=invite.company, defaults={"role": Role.ACCOUNTANT}
    )
    invite.accepted = True
    invite.save(update_fields=["accepted"])
    request.session["active_company_id"] = invite.company_id
    audit_log(request, "invite_accepted", company=invite.company, target=request.user.email)
    return redirect("fechamento", "atual")


@login_required
def trocar_empresa(request: HttpRequest) -> HttpResponseRedirect:
    company_id = request.POST.get("company_id")
    memberships = _active_memberships(request.user)
    if any(str(m.company_id) == company_id for m in memberships):
        request.session["active_company_id"] = int(company_id)
    return redirect("fechamento", "atual")


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _company_payload(company: Company) -> dict:
    """Todos os dados da empresa, sem senha nem segredo de MFA."""
    accounts = []
    for account in company.accounts.order_by("pk"):
        accounts.append(
            {
                "id": account.pk,
                "bank_id": account.bank_id,
                "branch": account.branch,
                "account_number": account.account_number,
                "opening_balance_cents": account.opening_balance_cents,
                "ledger_balance_cents": account.ledger_balance_cents,
                "is_primary": account.is_primary,
                "transactions": [
                    {
                        "id": t.pk,
                        "fitid": t.fitid,
                        "posted_on": _iso(t.posted_on),
                        "amount_cents": t.amount_cents,
                        "memo": t.memo,
                        "documents": list(t.documents),
                        "dedup_key": t.dedup_key,
                        "classification": t.classification,
                        "classification_direction": t.classification_direction,
                        "classified_note": t.classified_note,
                        "classified_by": t.classified_by,
                        "classified_at": _iso(t.classified_at),
                        "transfer_counterpart_id": t.transfer_counterpart_id,
                    }
                    for t in account.transactions.order_by("posted_on", "pk")
                ],
                "periods": [
                    {
                        "id": p.pk,
                        "start": _iso(p.start),
                        "end": _iso(p.end),
                        "opening_balance_cents": p.opening_balance_cents,
                        "closing_balance_cents": p.closing_balance_cents,
                        "closed": p.closed,
                        "closed_at": _iso(p.closed_at),
                    }
                    for p in account.periods.order_by("start")
                ],
            }
        )
    return {
        "id": company.pk,
        "name": company.name,
        "cnpj": company.cnpj,
        "cnpj_verified": company.cnpj_verified,
        "cnpj_verified_at": _iso(company.cnpj_verified_at),
        "cnpj_status": company.cnpj_status,
        "members": [
            {"email": m.user.email, "name": m.user.name, "role": m.role}
            for m in company.memberships.select_related("user").order_by("pk")
        ],
        "accounts": accounts,
        "items": [
            {
                "id": i.pk,
                "external_id": i.external_id,
                "source": i.source,
                "direction": i.direction,
                "amount_cents": i.amount_cents,
                "due_on": _iso(i.due_on),
                "issued_on": _iso(i.issued_on),
                "counterpart_doc": i.counterpart_doc,
                "counterpart_name": i.counterpart_name,
                "document_number": i.document_number,
                "gross_cents": i.gross_cents,
                "withholdings": i.withholdings,
                "status": i.status,
            }
            for i in company.items.order_by("due_on", "pk")
        ],
        "links": [
            {
                "id": ln.pk,
                "transaction_id": ln.transaction_id,
                "item_id": ln.item_id,
                "rule": ln.rule,
                "closed_with_difference": ln.closed_with_difference,
                "reason": ln.reason,
                "created_at": _iso(ln.created_at),
                "created_by": ln.created_by,
            }
            for ln in company.links.order_by("pk")
        ],
        "imports": [
            {
                "id": job.pk,
                "source": job.source,
                "file_name": job.file_name,
                "state": job.state,
                "result": job.result,
                "error": job.error,
                "created_by": job.created_by,
                "created_at": _iso(job.created_at),
            }
            for job in company.imports.order_by("pk")
        ],
        "audit": [
            {
                "id": entry.pk,
                "actor_email": entry.actor_email,
                "action": entry.action,
                "target": entry.target,
                "detail": entry.detail,
                "ip": entry.ip,
                "created_at": _iso(entry.created_at),
            }
            for entry in company.audit.order_by("pk")
        ],
    }


@login_required
def exportar_dados(request: HttpRequest) -> HttpResponse:
    """Exportação completa (LGPD): JSON com todos os dados das empresas do titular."""
    owned = [
        m.company
        for m in request.user.memberships.select_related("company")
        if m.role == Role.OWNER
    ]
    if not owned:
        return HttpResponse(status=403)
    payload = {
        "exported_at": timezone.now().isoformat(),
        "user": {
            "email": request.user.email,
            "name": request.user.name,
            "date_joined": _iso(request.user.date_joined),
        },
        "companies": [_company_payload(company) for company in owned],
    }
    audit_log(
        request,
        "data_export",
        company=owned[0],
        detail=f"{len(owned)} empresa(s)",
    )
    response = HttpResponse(
        json.dumps(payload, ensure_ascii=False, indent=2),
        content_type="application/json; charset=utf-8",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="conciliador-dados-{timezone.now():%Y%m%d}.json"'
    )
    return response


@login_required
def excluir_conta(request: HttpRequest) -> HttpResponse:
    """Exclusão da conta e das empresas das quais a pessoa é titular."""
    owned = [
        m.company
        for m in request.user.memberships.select_related("company")
        if m.role == Role.OWNER
    ]
    if not owned:
        return HttpResponse(status=403)
    if request.method == "POST":
        ip = ratelimit.client_ip(request)
        scope = f"{request.user.pk}:{ip}"
        if ratelimit.blocked("delete", scope, 5):
            return render(
                request,
                "accounts/excluir_conta.html",
                {
                    "companies": owned,
                    "error": "Muitas tentativas. Aguarde 15 minutos e tente de novo.",
                },
                status=429,
            )
        password = request.POST.get("password") or ""
        confirmation = (request.POST.get("confirm") or "").strip()
        if confirmation != "EXCLUIR":
            return render(
                request,
                "accounts/excluir_conta.html",
                {"companies": owned, "error": "Digite EXCLUIR para confirmar."},
                status=400,
            )
        if not request.user.check_password(password):
            ratelimit.hit("delete", scope, ratelimit.LOGIN_WINDOW)
            audit_log(request, "account_delete_failed")
            return render(
                request,
                "accounts/excluir_conta.html",
                {"companies": owned, "error": "Senha incorreta."},
                status=400,
            )
        user = request.user
        for company in owned:
            audit_log(request, "account_deleted", company=company, target=company.cnpj)
            company.delete()
        logout(request)
        user.delete()
        return redirect("landing")
    return render(request, "accounts/excluir_conta.html", {"companies": owned})
