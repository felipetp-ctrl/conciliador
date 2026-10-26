"""Middlewares de segurança do conciliador.

- ``ContentSecurityPolicyMiddleware``: cabeçalho CSP restritivo (scripts só do próprio site).
- ``MFAEnrollmentMiddleware``: MFA TOTP é obrigatório; sem segredo configurado, o usuário
  autenticado só acessa a tela de ativação e o logout.
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)

# Rotas que continuam acessíveis antes da ativação do MFA (evita laço de redirecionamento).
_MFA_EXEMPT_PREFIXES = (
    "/seguranca/mfa/",
    "/sair/",
    "/health",
    "/static/",
    "/media/",
)

# Rotas acessíveis enquanto o usuário ainda não tem empresa (deploy vazio/superusuário).
_COMPANY_EXEMPT_PREFIXES = (
    "/empresa/",
    "/sair/",
    "/seguranca/mfa/",
    "/health",
    "/static/",
    "/media/",
)


class ContentSecurityPolicyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        response.headers.setdefault("Content-Security-Policy", _CSP)
        return response


class MFAEnrollmentMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and not user.mfa_secret
            and not request.path.startswith(_MFA_EXEMPT_PREFIXES)
        ):
            return redirect("mfa_setup")
        return self.get_response(request)


class CompanySetupMiddleware:
    """Sem empresa, o usuário autenticado vai cadastrar a primeira antes de usar o painel.

    Acontece no deploy vazio (superusuário criado por ``createsuperuser``) e se alguém
    ficar sem membresia. Sem isso, ``_company_of`` levantaria erro e a tela daria 500.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and user.mfa_secret
            and not user.memberships.exists()
            and not request.path.startswith(_COMPANY_EXEMPT_PREFIXES)
        ):
            return redirect("empresa")
        return self.get_response(request)
