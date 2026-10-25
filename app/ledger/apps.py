from django.apps import AppConfig


class LedgerConfig(AppConfig):
    name = "ledger"
    label = "ledger"

    def ready(self) -> None:
        from . import signals  # noqa: F401  (registra os PRAGMAs do SQLite)
