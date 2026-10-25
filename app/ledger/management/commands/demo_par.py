"""Monta uma conta de demonstração com os quatro estados da conciliação.

Nenhum dado real de cliente: os documentos vêm do corpus público (NF-e de exemplo) e o
extrato é sintético, gerado com ``conciliador_synth``. O extrato é criado para casar com
os documentos — o mesmo valor, a mesma contraparte no histórico e a data perto do
vencimento — e as linhas que sobram viram "só no banco", "pendente" e "atrasado".

Idempotente: rodar de novo não duplica conta, lançamento nem item.
"""

from __future__ import annotations

import tempfile
from datetime import timedelta
from pathlib import Path

from accounts.models import seed_demo_user
from conciliador_synth.ofx import SynthTxn, make_ofx
from django.core.management.base import BaseCommand
from django.utils import timezone

from ledger import ingest
from ledger.models import BankAccount, Company, ExpectedItem

DEMO_CNPJ = "11222333000181"
BANK_ID = "001"
BRANCH = "1234"
ACCOUNT = "12345-6"

# CSV de contas a pagar: dois fornecedores com vencimento próximo e um já vencido.
CSV_HEADER = (
    "tipo;valor;vencimento;contraparte_nome;contraparte_documento;documento_numero;descricao"
)
CSV_CONTAS = (
    CSV_HEADER
    + """
pagar;250,90;{pago};Fornecedor Exemplo SA;12.345.678/0001-95;2002;Compra de exemplo
pagar;1.480,00;{aberto};Aluguel Centro Ltda;45.723.174/0001-10;2003;Aluguel do mês
pagar;389,90;{vencido};Energia Paulista SA;90.876.543/0001-60;2004;Energia elétrica
"""
)


class Command(BaseCommand):
    help = "Cria a conta de demonstração com pares banco ⟷ documento (dados sintéticos)."

    def handle(self, *args, **options):
        company, _ = Company.objects.get_or_create(
            cnpj=DEMO_CNPJ, defaults={"name": "Oficina Exemplo Ltda"}
        )
        seed_demo_user(company)
        today = timezone.localdate()
        due_pago, due_aberto, due_vencido = (
            today - timedelta(days=3),
            today + timedelta(days=12),
            today - timedelta(days=25),
        )

        # 1. Contas a pagar (CSV sintético) — o item "pago" casa com um débito do extrato.
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "conciliador-demo-contas.csv"
            csv_path.write_text(
                CSV_CONTAS.format(
                    pago=due_pago.strftime("%d/%m/%Y"),
                    aberto=due_aberto.strftime("%d/%m/%Y"),
                    vencido=due_vencido.strftime("%d/%m/%Y"),
                ),
                encoding="utf-8",
            )
            csv_report = ingest.ingest_csv(csv_path, company)

            # 2. Documentos reais do corpus (NF-e) — até 3 notas a receber.
            reais = list(
                ExpectedItem.objects.filter(
                    company=company,
                    source="nfe",
                    direction="inflow",
                    counterpart_doc__regex=r"^[0-9]{14}$",
                ).order_by("due_on")[:3]
            )

            # 3. Extrato sintético: um crédito por nota + o pagamento do fornecedor + tarifa.
            txns: list[SynthTxn] = []
            for n, item in enumerate(reais, start=1):
                posted = item.due_on + timedelta(days=1 if n % 2 else 0)
                txns.append(
                    SynthTxn(
                        posted_on=posted,
                        amount_cents=item.amount_cents,
                        memo=f"PIX RECEBIDO {item.counterpart_doc} {item.counterpart_name}"[:120],
                        fitid=f"demo-rec-{n}",
                    )
                )
            txns.append(
                SynthTxn(
                    posted_on=due_pago,
                    amount_cents=-25090,
                    memo="PAGTO BOLETO 12.345.678/0001-95 FORNECEDOR EXEMPLO",
                    fitid="demo-pag-1",
                )
            )
            txns.append(
                SynthTxn(
                    posted_on=today - timedelta(days=1),
                    amount_cents=-3990,
                    memo="TARIFA PACOTE DE SERVICOS",
                    fitid="demo-tarifa-1",
                )
            )
            txns.sort(key=lambda t: t.posted_on)

            opening = 0
            closing = opening + sum(t.amount_cents for t in txns)
            ofx = make_ofx(
                txns,
                version=2,
                encoding="utf-8",
                ledger_balance_cents=closing,
                start=min(t.posted_on for t in txns),
                end=max(t.posted_on for t in txns),
                bank_id=BANK_ID,
                branch=BRANCH,
                account=ACCOUNT,
            )
            ofx_path = Path(tmp) / "conciliador-demo-extrato.ofx"
            ofx_path.write_bytes(ofx)
            ofx_report = ingest.ingest_ofx(ofx_path, company)

        # 4. Saldo inicial conhecido (0) → o fechamento do extrato pode ser conferido.
        BankAccount.objects.filter(
            company=company, bank_id=BANK_ID, branch=BRANCH, account_number=ACCOUNT
        ).update(opening_balance_cents=opening, is_primary=True)

        self.stdout.write(f"contas a pagar: {csv_report}")
        self.stdout.write(f"extrato: {ofx_report}")
        self.stdout.write(
            f"{len(reais)} nota(s) real(is) do corpus no extrato; conta {ACCOUNT} é a principal"
        )
        self.stdout.write(f"saldo final do extrato: {closing} centavos")
