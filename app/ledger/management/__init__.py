"""Ingere o corpus público no banco local (dados de teste, nenhum dado real de cliente)."""

from django.core.management.base import BaseCommand

from ledger import ingest
from ledger.models import Company


class Command(BaseCommand):
    help = "Ingere o corpus OFX/NF-e/NFS-e na empresa de demonstração."

    def add_arguments(self, parser):
        parser.add_argument("corpus_dir", nargs="?", default="")

    def handle(self, *args, **options):
        corpus_dir = options["corpus_dir"] or (
            "/Users/felipetomepereira/Projects/conciliacao-IA-corpus/samples"
        )
        company, _ = Company.objects.get_or_create(
            cnpj="11222333000181", defaults={"name": "Oficina Exemplo Ltda"}
        )
        report = ingest.ingest_corpus(corpus_dir, company)
        ok = [r for r in report if r["ok"]]
        bad = [r for r in report if not r["ok"]]
        self.stdout.write(f"{len(report)} arquivos: {len(ok)} ok, {len(bad)} recusados")
        for r in ok:
            self.stdout.write(f"  ✓ {r['file']} — {r.get('txns', r.get('items'))}")
        for r in bad:
            self.stdout.write(f"  ✗ {r['file']} — {r.get('error')}")
        from ledger.services import reconcile

        ctx = reconcile(company)
        self.stdout.write(
            f"itens: {len(ctx['items'])} · a confirmar: {ctx['counts']['a_confirmar']} · "
            f"não identificado: {ctx['totals']['n_nid']}"
        )
