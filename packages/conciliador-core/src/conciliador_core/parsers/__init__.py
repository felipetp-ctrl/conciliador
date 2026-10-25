"""Leitores de arquivos (OFX, ...)."""

from conciliador_core.parsers.ofx import MAX_FILE_BYTES, parse_ofx

__all__ = ["MAX_FILE_BYTES", "parse_ofx"]
