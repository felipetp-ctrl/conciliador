"""Interpretação de valores monetários em reais, sempre em centavos inteiros."""

import re

from conciliador_core.errors import ParseError

_CHARS = re.compile(r"[0-9.,]+")
_MAX_INTEGER_DIGITS = 15


def _invalid(text: str) -> ParseError:
    return ParseError("invalid_amount", f"Valor monetário inválido: {text!r}.")


def parse_brl_amount(text: str) -> int:
    """Converte um texto como ``"1.234,56"`` ou ``"1234.56"`` em centavos (com sinal)."""
    raw = text.strip()
    negative = raw.startswith("-")
    if raw[:1] in ("-", "+"):
        raw = raw[1:]
    if not _CHARS.fullmatch(raw):
        raise _invalid(text)

    last = max(raw.rfind(","), raw.rfind("."))
    decimals = ""
    integer = raw
    thousands: str | None = None
    if last >= 0:
        tail = raw[last + 1 :]
        if len(tail) in (1, 2):
            decimals = tail
            integer = raw[:last]
            other = "." if raw[last] == "," else ","
            if "," in integer and "." in integer:
                raise _invalid(text)
            if raw[last] in integer:
                raise _invalid(text)
            thousands = other if other in integer else None
        elif len(tail) == 3:
            if "," in raw and "." in raw:
                raise _invalid(text)
            thousands = raw[last]
        else:
            raise _invalid(text)

    if thousands is not None:
        groups = integer.split(thousands)
        if not (1 <= len(groups[0]) <= 3 and all(len(g) == 3 for g in groups[1:])):
            raise _invalid(text)
        integer = "".join(groups)
    if not integer or not integer.isdigit():
        raise _invalid(text)

    if len(integer) > _MAX_INTEGER_DIGITS:
        raise _invalid(text)
    cents = int(integer) * 100 + int(decimals.ljust(2, "0") or "0")
    return -cents if negative else cents
