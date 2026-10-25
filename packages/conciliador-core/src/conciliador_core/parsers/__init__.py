"""Leitores de arquivos (OFX, NF-e, ...)."""

from conciliador_core.parsers._limits import MAX_FILE_BYTES
from conciliador_core.parsers._xml import safe_parse_xml
from conciliador_core.parsers.fiscal import FiscalParseResult, parse_fiscal_xml
from conciliador_core.parsers.ofx import parse_ofx

__all__ = [
    "MAX_FILE_BYTES",
    "FiscalParseResult",
    "parse_fiscal_xml",
    "parse_ofx",
    "safe_parse_xml",
]
