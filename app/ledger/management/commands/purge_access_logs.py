"""Apaga registros de acesso com mais de 6 meses (retenção LGPD/Marco Civil).

Roda no startup do App Service e pode ser chamado à mão:
``python app/manage.py purge_access_logs``.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from ledger.audit import ACCESS_ACTIONS
from ledger.models import AuditLog


class Command(BaseCommand):
    help = "Apaga logs de acesso/segurança com mais de 6 meses; preserva a auditoria de negócio."

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=183)
        deleted, _ = AuditLog.objects.filter(
            action__in=ACCESS_ACTIONS, created_at__lt=cutoff
        ).delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"{deleted} registro(s) de acesso apagados (anteriores a {cutoff:%d/%m/%Y})."
            )
        )
