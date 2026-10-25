"""Autenticação, MFA (TOTP), convite de contador e troca de empresa."""

from __future__ import annotations

import pyotp
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect, render
from ledger.models import Company

from .models import Invite, Membership, Role, User


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
        company = Company.objects.create(name=f"Empresa de {name}", cnpj=_placeholder_cnpj(user))
        Membership.objects.create(user=user, company=company, role=Role.OWNER)
        login(request, user)
        request.session["active_company_id"] = company.pk
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
            request.session.pop("pending_invite_token", None)
        return redirect("fechamento", "atual")
    return render(request, "accounts/signup.html")


def _placeholder_cnpj(user: User) -> str:
    # CNPJ provisório derivado do id (só até a pessoa informar o real em "Empresa").
    return f"00{user.pk:012d}"[:14]


def login_view(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        password = request.POST.get("password") or ""
        user = authenticate(request, username=email, password=password)
        if user is None:
            return render(
                request,
                "accounts/login.html",
                {"error": "E-mail ou senha incorretos.", "email": email},
                status=401,
            )
        if user.mfa_secret:
            request.session["mfa_pending_user_id"] = user.pk
            return redirect("mfa_verify")
        login(request, user)
        return redirect("fechamento", "atual")
    return render(request, "accounts/login.html")


def mfa_verify(request: HttpRequest) -> HttpResponse:
    user_id = request.session.get("mfa_pending_user_id")
    user = User.objects.filter(pk=user_id).first() if user_id else None
    if user is None:
        return redirect("login")
    if request.method == "POST":
        code = (request.POST.get("code") or "").strip()
        if pyotp.TOTP(user.mfa_secret).verify(code):
            login(request, user)
            request.session.pop("mfa_pending_user_id", None)
            return redirect("fechamento", "atual")
        return render(request, "accounts/mfa.html", {"error": "Código inválido."}, status=401)
    return render(request, "accounts/mfa.html")


def logout_view(request: HttpRequest) -> HttpResponseRedirect:
    logout(request)
    return redirect("login")


@login_required
def mfa_setup(request: HttpRequest) -> HttpResponse:
    """Ativa/confirma o MFA (TOTP). O segredo fica na sessão até o código ser confirmado."""
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
            return redirect("mfa_setup")
        return render(
            request,
            "accounts/mfa_setup.html",
            {"error": "Código inválido.", "pending": pending, "otpauth": _otpauth(user, pending)},
            status=400,
        )
    if request.method == "POST" and request.POST.get("action") == "disable":
        user.mfa_secret = ""
        user.save(update_fields=["mfa_secret"])
        request.session.pop("mfa_pending_secret", None)
        return redirect("mfa_setup")
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


@login_required
def convites(request: HttpRequest) -> HttpResponse:
    company, role = resolve_company(request)
    if role != Role.OWNER:
        return HttpResponse(status=403)
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        Invite.objects.create(
            company=company, email=email, created_by=request.user, token=Invite.new_token()
        )
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
    return redirect("fechamento", "atual")


@login_required
def trocar_empresa(request: HttpRequest) -> HttpResponseRedirect:
    company_id = request.POST.get("company_id")
    memberships = _active_memberships(request.user)
    if any(str(m.company_id) == company_id for m in memberships):
        request.session["active_company_id"] = int(company_id)
    return redirect("fechamento", "atual")
