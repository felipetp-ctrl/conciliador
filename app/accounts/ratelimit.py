"""Limite de tentativas de login e de código MFA.

Usa o cache do Django (LocMem no piloto de um worker). As chaves são hashes para não
guardar e-mail nem IP em texto no cache. O limite é por e-mail e por IP: um ataque a
uma conta específica não bloqueia as outras, e um ataque distribuído ainda esbarra no IP.
"""

from __future__ import annotations

import hashlib

from django.core.cache import cache
from django.http import HttpRequest

LOGIN_LIMIT = 5
# Limite de IP alto de propósito: no App Service todos podem chegar pelo mesmo proxy.
LOGIN_IP_LIMIT = 100
LOGIN_WINDOW = 15 * 60
MFA_LIMIT = 5
MFA_WINDOW = 5 * 60
SIGNUP_LIMIT = 10
SIGNUP_WINDOW = 60 * 60


def _key(scope: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]
    return f"rl:{scope}:{digest}"


def blocked(scope: str, value: str, limit: int) -> bool:
    return int(cache.get(_key(scope, value), 0)) >= limit


def hit(scope: str, value: str, window: int) -> None:
    key = _key(scope, value)
    if cache.add(key, 1, timeout=window):
        return
    try:
        cache.incr(key)
    except ValueError:  # expirou entre o add e o incr
        cache.set(key, 1, timeout=window)


def clear(scope: str, value: str) -> None:
    cache.delete(_key(scope, value))


def client_ip(request: HttpRequest) -> str:
    """IP do cliente.

    Usa ``REMOTE_ADDR``: ``X-Forwarded-For`` pode ser forjado pelo cliente. Se o app
    estiver atrás de um proxy confiável que sobrescreve o cabeçalho, troque aqui.
    """
    return request.META.get("REMOTE_ADDR", "")
