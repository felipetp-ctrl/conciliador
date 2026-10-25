import pytest
from conciliador_core.text import clean_text, has_unsafe_chars

BIDI = [chr(c) for c in (*range(0x202A, 0x202F), *range(0x2066, 0x206A))]
ZERO_WIDTH = ["​", "‌", "‍", "﻿"]
C1 = [chr(c) for c in range(0x80, 0xA0)]


@pytest.mark.parametrize("ch", BIDI + ZERO_WIDTH)
def test_bidi_and_zero_width_are_removed(ch: str) -> None:
    assert clean_text(f"FORNE{ch}CEDOR") == "FORNECEDOR"


@pytest.mark.parametrize("ch", C1 + ["\x00", "\x1f", "\x7f", " ", " ", "\t", "\n"])
def test_controls_and_separators_become_space(ch: str) -> None:
    assert clean_text(f"PIX{ch}RECEBIDO") == "PIX RECEBIDO"


def test_collapses_and_strips() -> None:
    assert clean_text("  a    b‮  ") == "a b"
    assert clean_text("Ação São João") == "Ação São João"


@pytest.mark.parametrize("ch", BIDI + ZERO_WIDTH + C1 + ["\x00", "\x7f", " "])
def test_has_unsafe_chars(ch: str) -> None:
    assert has_unsafe_chars(f"12{ch}3")
    assert not has_unsafe_chars("1.234,56 R$ Ação")
