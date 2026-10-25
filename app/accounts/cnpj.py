"""Checagem de CNPJ: dígito verificador (core) + consulta oficial na Receita (BrasilAPI).

A checagem de dígito é local e obrigatória. A consulta oficial confirma que o CNPJ
existe e está ativo; se a rede falhar, a validação não trava o cadastro — devolve
``found=None`` com uma mensagem para o dono revalidar depois.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from conciliador_core.documents import is_valid_cnpj, only_alnum

_URL = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
_TIMEOUT = 8


@dataclass(frozen=True)
class CnpjCheck:
    cnpj: str
    valid_dv: bool
    found: bool | None  # None = não consultado (erro de rede)
    active: bool | None
    razao_social: str
    situacao: str
    error: str  # pt-BR; vazio quando ok


def _fetch(cnpj: str) -> tuple[int, dict]:
    req = urllib.request.Request(_URL.format(cnpj=cnpj), headers={"User-Agent": "conciliador/0.1"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def check_cnpj(cnpj: str) -> CnpjCheck:
    """Valida o dígito e, se válido, consulta a Receita. Nunca levanta exceção de rede."""
    s = only_alnum(cnpj)
    if not is_valid_cnpj(s):
        return CnpjCheck(
            s, False, None, None, "", "", "CNPJ inválido — confira o dígito verificador."
        )
    try:
        _status, payload = _fetch(s)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return CnpjCheck(s, True, False, None, "", "", "CNPJ não encontrado na Receita.")
        return CnpjCheck(
            s, True, None, None, "", "", "Erro ao consultar a Receita (tente de novo)."
        )
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return CnpjCheck(
            s,
            True,
            None,
            None,
            "",
            "",
            "Não foi possível consultar a Receita agora — salvamos e você revalida depois.",
        )
    situacao = payload.get("descricao_situacao_cadastral") or str(
        payload.get("situacao_cadastral", "")
    )
    active = payload.get("situacao_cadastral") == 1 or str(situacao).lower() == "ativa"
    return CnpjCheck(
        cnpj=s,
        valid_dv=True,
        found=True,
        active=active,
        razao_social=payload.get("razao_social", ""),
        situacao=situacao,
        error="",
    )
