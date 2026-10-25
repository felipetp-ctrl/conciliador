"""Context processors do conciliador (dev: usuário de demonstração sem auth)."""

from types import SimpleNamespace


def user(request):
    # Autenticação (com MFA) entra no Plano 2; por ora, um usuário de demonstração.
    if not hasattr(request, "user"):
        request.user = SimpleNamespace(get_full_name=lambda: "Ana Souza")
    return {}
