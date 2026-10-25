"""Leitores de arquivos (OFX, NF-e, ...)."""

from conciliador_core.parsers._limits import MAX_FILE_BYTES, MAX_XML_BYTES
from conciliador_core.parsers._xml import safe_parse_xml
from conciliador_core.parsers.csv_items import (
    CsvParseResult,
    RowError,
    parse_items_csv,
    template_csv,
)
from conciliador_core.parsers.fiscal import FiscalParseResult, parse_fiscal_xml
from conciliador_core.parsers.ofx import parse_ofx

__all__ = [
    "MAX_FILE_BYTES",
    "MAX_XML_BYTES",
    "CsvParseResult",
    "FiscalParseResult",
    "RowError",
    "parse_fiscal_xml",
    "parse_items_csv",
    "parse_ofx",
    "safe_parse_xml",
    "template_csv",
]
