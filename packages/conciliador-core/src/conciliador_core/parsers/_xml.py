"""Leitura segura de XML: sem DTD, sem entidades e com limite de tamanho."""

from xml.etree.ElementTree import Element  # nosec B405

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import ParseError, fromstring

from conciliador_core.errors import ParseError as CoreParseError
from conciliador_core.parsers._limits import MAX_XML_BYTES


def safe_parse_xml(data: bytes) -> Element:
    """Interpreta ``data`` como XML recusando DTD, entidades e referências externas.

    Levanta ``ParseError("too_large")`` acima de ``MAX_XML_BYTES`` (2 MB),
    ``ParseError("xml_forbidden")`` para DTD/entidades e ``ParseError("invalid_format")``
    para qualquer outro XML malformado.
    """
    if len(data) > MAX_XML_BYTES:
        raise CoreParseError("too_large", "Arquivo XML maior que o limite de 2 MB.")
    try:
        return fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except DefusedXmlException as exc:
        raise CoreParseError(
            "xml_forbidden", "O XML contém DTD ou entidades, que não são permitidas."
        ) from exc
    except ParseError as exc:
        raise CoreParseError("invalid_format", "XML malformado.") from exc
    except Exception as exc:  # nenhuma outra falha pode escapar para entrada ruim
        raise CoreParseError("invalid_format", "XML inválido.") from exc
