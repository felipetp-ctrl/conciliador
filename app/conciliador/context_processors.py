"""Context processors do conciliador (globais de template)."""

from __future__ import annotations

from accounts.views import resolve_company


def globals(request):
    """Injeta a empresa/visão ativas e os membros para o template base."""
    company, role = resolve_company(request)
    return {
        "active_company": company,
        "active_role": role,
    }
