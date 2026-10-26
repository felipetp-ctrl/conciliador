"""Gravação do log de auditoria (append-only)."""

from __future__ import annotations

from django.http import HttpRequest

from . import models


def log(
    request: HttpRequest,
    action: str,
    *,
    company: models.Company | None = None,
    target: str = "",
    detail: str = "",
    actor_email: str = "",
) -> None:
    """Registra a ação com o ator, a empresa e o IP.

    Nunca grave conteúdo financeiro nem documentos completos: o log serve para saber
    *quem fez o quê*, não para duplicar os dados do cliente.
    """
    user = getattr(request, "user", None)
    actor = user if getattr(user, "is_authenticated", False) else None
    email = actor_email or (getattr(actor, "email", "") or "")
    ip = request.META.get("REMOTE_ADDR") or None
    models.AuditLog.objects.create(
        company=company,
        actor=actor,
        actor_email=email[:254],
        action=action[:40],
        target=target[:160],
        detail=detail[:255],
        ip=ip,
    )
