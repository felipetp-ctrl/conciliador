"""Códigos de recuperação do MFA: uso único, guardados só como hash SHA-256."""

from __future__ import annotations

import hashlib
import secrets

from django.utils import timezone

from .models import User

COUNT = 8


def _normalize(code: str) -> str:
    return "".join(c for c in code if c.isalnum()).upper()


def _hash(code: str) -> str:
    return hashlib.sha256(_normalize(code).encode("utf-8")).hexdigest()


def generate(user: User) -> list[str]:
    """Gera um novo conjunto e invalida todos os códigos anteriores do usuário."""
    from .models import RecoveryCode

    user.recovery_codes.all().delete()
    codes = []
    for _ in range(COUNT):
        raw = secrets.token_hex(5).upper()
        code = f"{raw[:5]}-{raw[5:]}"
        RecoveryCode.objects.create(user=user, code_hash=_hash(code))
        codes.append(code)
    return codes


def verify(user: User, code: str) -> bool:
    """Marca o código como usado se ele existir e estiver livre. Nunca reutiliza."""
    if not _normalize(code):
        return False
    entry = user.recovery_codes.filter(code_hash=_hash(code), used_at__isnull=True).first()
    if entry is None:
        return False
    entry.used_at = timezone.now()
    entry.save(update_fields=["used_at"])
    return True
