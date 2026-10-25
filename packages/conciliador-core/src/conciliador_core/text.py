"""Normalização de texto vindo de arquivos (histórico do OFX, nomes, descrições).

Única fonte das classes de caracteres perigosos, usada por todos os leitores:

- invisíveis (removidos): controles bidirecionais U+202A–U+202E e U+2066–U+2069 e
  caracteres de largura zero U+200B–U+200D e U+FEFF;
- controles (viram espaço): C0 (U+0000–U+001F), DEL, C1 (U+0080–U+009F) e os separadores
  de linha/parágrafo U+2028 e U+2029.
"""

import re

_INVISIBLE = "\u200b-\u200d\u202a-\u202e\u2066-\u2069\ufeff"
_CONTROLS = "\x00-\x1f\x7f-\x9f\u2028\u2029"
_REMOVE = re.compile(f"[{_INVISIBLE}]")
_TO_SPACE = re.compile(f"[{_CONTROLS}]")
_UNSAFE = re.compile(f"[{_INVISIBLE}{_CONTROLS}]")
_SPACES = re.compile(r"\s+")


def clean_text(value: str) -> str:
    """Remove invisíveis, troca controles por espaço, colapsa espaços e apara as pontas."""
    text = _TO_SPACE.sub(" ", _REMOVE.sub("", value))
    return _SPACES.sub(" ", text).strip()


def has_unsafe_chars(value: str) -> bool:
    """True se ``value`` tem algum caractere invisível ou de controle (inclusive tab/quebra)."""
    return _UNSAFE.search(value) is not None
