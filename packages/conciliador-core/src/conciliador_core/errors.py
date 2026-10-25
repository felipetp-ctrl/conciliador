"""Erros do conciliador-core."""


class ParseError(Exception):
    """Falha ao ler ou interpretar um arquivo ou valor.

    ``code`` é um identificador estável (ex.: ``too_large``, ``invalid_amount``);
    ``message`` é a mensagem em português do Brasil voltada ao usuário.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
