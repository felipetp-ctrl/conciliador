"""PRAGMAs do SQLite para o piloto no App Service.

O SQLite do piloto roda com **WAL** (leitura e escrita concorrem sem travar uma à
outra) e ``busy_timeout`` (espera em vez de estourar "database is locked" quando
duas requisições escrevem juntas). Em PostgreSQL este módulo não faz nada.
"""

from __future__ import annotations

from django.db.backends.signals import connection_created
from django.dispatch import receiver


@receiver(connection_created)
def _sqlite_pragmas(sender, connection, **kwargs) -> None:  # noqa: ANN001
    if connection.vendor != "sqlite":
        return
    name = str(connection.settings_dict.get("NAME", ""))
    if name == ":memory:" or "mode=memory" in name:
        return
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA busy_timeout=5000;")
