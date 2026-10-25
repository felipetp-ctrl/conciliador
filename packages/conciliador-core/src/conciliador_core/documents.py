"""CPF e CNPJ (inclusive o CNPJ alfanumérico, vigente desde julho de 2026)."""

import re

_CNPJ_W1 = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
_CNPJ_W2 = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
_NON_ALNUM = re.compile(r"[^0-9A-Za-z]")
_CNPJ_BODY = re.compile(r"[0-9A-Z]{12}[0-9]{2}")

_B = r"(?<![0-9A-Za-z])"
_E = r"(?![0-9A-Za-z])"
_CANDIDATE = re.compile(
    rf"{_B}(?:"
    r"[0-9A-Z]{2}\.[0-9A-Z]{3}\.[0-9A-Z]{3}/[0-9A-Z]{4}-[0-9]{2}"
    r"|[0-9]{3}\.[0-9]{3}\.[0-9]{3}-[0-9]{2}"
    r"|[0-9A-Z]{14}"
    r"|[0-9]{11}"
    rf"){_E}",
    re.IGNORECASE,
)


def only_alnum(text: str) -> str:
    """Remove pontuação e devolve o texto em maiúsculas."""
    return _NON_ALNUM.sub("", text).upper()


def _cpf_digit(digits: list[int]) -> int:
    weight = len(digits) + 1
    total = sum(d * (weight - i) for i, d in enumerate(digits))
    r = total % 11
    return 0 if r < 2 else 11 - r


def is_valid_cpf(value: str) -> bool:
    s = only_alnum(value)
    if len(s) != 11 or not s.isdigit() or len(set(s)) == 1:
        return False
    digits = [int(c) for c in s]
    return _cpf_digit(digits[:9]) == digits[9] and _cpf_digit(digits[:10]) == digits[10]


def _cnpj_digit(chars: str, weights: tuple[int, ...]) -> int:
    r = sum((ord(c) - 48) * w for c, w in zip(chars, weights, strict=True)) % 11
    return 0 if r < 2 else 11 - r


def is_valid_cnpj(value: str) -> bool:
    s = only_alnum(value)
    if len(s) != 14 or not _CNPJ_BODY.fullmatch(s) or len(set(s)) == 1:
        return False
    return _cnpj_digit(s[:12], _CNPJ_W1) == int(s[12]) and _cnpj_digit(s[:13], _CNPJ_W2) == int(
        s[13]
    )


def cnpj_root(cnpj: str) -> str:
    """Raiz do CNPJ: os 8 primeiros caracteres, normalizados."""
    return only_alnum(cnpj)[:8]


def find_documents(text: str) -> tuple[str, ...]:
    """CPFs/CNPJs válidos no texto, normalizados, na ordem de aparição (sem repetir)."""
    found: list[str] = []
    for match in _CANDIDATE.finditer(text):
        norm = only_alnum(match.group())
        valid = is_valid_cpf(norm) if len(norm) == 11 else is_valid_cnpj(norm)
        if valid and norm not in found:
            found.append(norm)
    return tuple(found)


def mask_cpf(cpf: str) -> str:
    """Mascara um CPF no formato ``***.982.247-**``."""
    s = only_alnum(cpf)
    return f"***.{s[3:6]}.{s[6:9]}-**"
