"""Modelos de dados do conciliador (Plano 2).

Espelham os modelos do núcleo ``conciliador_core.models`` (centavos inteiros) e
acrescentam a camada de persistência e o vínculo confirmado (``Link``).
Isolamento por empresa via FKs; RLS em nível de banco entra depois.
"""

from __future__ import annotations

from django.db import models


class Company(models.Model):
    name = models.CharField(max_length=200)
    cnpj = models.CharField(max_length=14, unique=True)
    # resultado da checagem oficial na Receita (dígito + consulta externa)
    cnpj_verified = models.BooleanField(default=False)
    cnpj_verified_at = models.DateTimeField(null=True, blank=True)
    cnpj_status = models.CharField(max_length=40, blank=True, default="")

    class Meta:
        verbose_name = "empresa"
        verbose_name_plural = "empresas"

    def __str__(self) -> str:
        return self.name


class BankAccount(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="accounts")
    bank_id = models.CharField(max_length=100, blank=True, default="")
    branch = models.CharField(max_length=20, blank=True, default="")
    account_number = models.CharField(max_length=40)
    # saldo final do último extrato importado (LEDGERBAL / ledger_balance_cents)
    ledger_balance_cents = models.IntegerField(null=True, blank=True)
    # saldo antes do primeiro lançamento importado; o OFX não traz, então fica nulo até
    # alguém informar. Só com ele dá para conferir o fechamento.
    opening_balance_cents = models.IntegerField(null=True, blank=True)
    # conta que abre por padrão no painel (a "conta principal" da empresa)
    is_primary = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "bank_id", "branch", "account_number"], name="uniq_conta"
            )
        ]

    @property
    def label(self) -> str:
        bank = self.bank_id or "Banco"
        return f"{bank} · {self.account_number}"

    def __str__(self) -> str:
        return self.label


class BankTransaction(models.Model):
    account = models.ForeignKey(BankAccount, on_delete=models.CASCADE, related_name="transactions")
    fitid = models.CharField(max_length=100, blank=True, default="")
    posted_on = models.DateField()
    amount_cents = models.IntegerField()
    memo = models.TextField(blank=True, default="")
    # CPF/CNPJ encontrados no histórico (tuple[str, ...] no núcleo)
    documents = models.JSONField(default=list)
    dedup_key = models.CharField(max_length=64, db_index=True, default="")
    # Classificação de um lançamento "só no banco" (tarifa, juros, rendimento, transferência…).
    # Vazia quando o lançamento ainda não foi explicado.
    classification = models.CharField(max_length=20, blank=True, default="")
    # Direção da despesa/receita classificada ("inflow"/"outflow"); vazia para transferência.
    classification_direction = models.CharField(max_length=10, blank=True, default="")
    classified_note = models.CharField(max_length=200, blank=True, default="")
    classified_by = models.CharField(max_length=200, blank=True, default="")
    classified_at = models.DateTimeField(null=True, blank=True)
    # Na transferência entre contas, o lançamento-espelho na outra conta (fora do razão).
    transfer_counterpart = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["posted_on", "id"]
        indexes = [models.Index(fields=["account", "posted_on"])]

    @property
    def is_classified(self) -> bool:
        return bool(self.classification)

    def __str__(self) -> str:
        return f"{self.posted_on} {self.amount_cents} {self.memo[:40]}"


class ExpectedItem(models.Model):
    SOURCE_CHOICES = [("nfe", "NF-e"), ("nfse", "NFS-e"), ("csv", "CSV"), ("manual", "Manual")]
    DIRECTION_CHOICES = [("inflow", "a receber"), ("outflow", "a pagar")]
    STATUS_CHOICES = [("open", "aberto"), ("cancelled", "cancelado")]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="items")
    # id do núcleo (ex.: "nfe:<chave>:1"); único dentro da empresa, não globalmente:
    # a mesma nota pode ser emitida para duas empresas.
    external_id = models.CharField(max_length=120)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES)
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES)
    amount_cents = models.PositiveIntegerField()  # líquido, sempre positivo
    due_on = models.DateField()
    issued_on = models.DateField(null=True, blank=True)
    counterpart_doc = models.CharField(max_length=20, blank=True, default="")
    counterpart_name = models.CharField(max_length=200, blank=True, default="")
    document_number = models.CharField(max_length=60, blank=True, default="")
    gross_cents = models.PositiveIntegerField(null=True, blank=True)
    # [(nome_da_retencao, centavos), ...]
    withholdings = models.JSONField(default=list)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="open")

    class Meta:
        ordering = ["due_on", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "external_id"], name="uniq_item_company_external"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.external_id} {self.amount_cents}"


class RejectedLink(models.Model):
    """Par recusado por uma pessoa, para a sugestão não voltar a aparecer."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="rejected")
    transaction = models.ForeignKey(
        BankTransaction, on_delete=models.CASCADE, related_name="rejected"
    )
    item = models.ForeignKey(ExpectedItem, on_delete=models.CASCADE, related_name="rejected")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["transaction", "item"], name="uniq_rejected")
        ]


class Period(models.Model):
    """Fechamento mensal de uma conta: saldo inicial → movimentações → saldo final."""

    account = models.ForeignKey(BankAccount, on_delete=models.CASCADE, related_name="periods")
    start = models.DateField()
    end = models.DateField()
    opening_balance_cents = models.IntegerField(null=True, blank=True)
    closing_balance_cents = models.IntegerField(null=True, blank=True)
    closed = models.BooleanField(default=False)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["start"]
        constraints = [
            models.UniqueConstraint(fields=["account", "start", "end"], name="uniq_periodo"),
        ]

    @property
    def label(self) -> str:
        return f"{self.start:%m/%Y}"

    def __str__(self) -> str:
        return f"{self.account_id} {self.start:%Y-%m}"


class ImportJob(models.Model):
    """Um arquivo enviado pelo dono, com o resultado do processamento."""

    SOURCE_CHOICES = [("ofx", "OFX"), ("nfe", "NF-e"), ("nfse", "NFS-e"), ("csv", "CSV")]
    STATE_CHOICES = [("processing", "processando"), ("done", "concluído"), ("error", "erro")]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="imports")
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES)
    file_name = models.CharField(max_length=255)
    state = models.CharField(max_length=10, choices=STATE_CHOICES, default="processing")
    result = models.CharField(max_length=255, blank=True, default="")
    error = models.CharField(max_length=255, blank=True, default="")
    created_by = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.source} {self.file_name} ({self.state})"


class Link(models.Model):
    """Vínculo confirmado por uma pessoa entre um lançamento e um item."""

    RULE_CHOICES = [
        ("document", "documento"),
        ("number", "número"),
        ("unique", "único"),
        ("manual", "manual"),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="links")
    transaction = models.ForeignKey(BankTransaction, on_delete=models.CASCADE, related_name="links")
    item = models.ForeignKey(ExpectedItem, on_delete=models.CASCADE, related_name="links")
    rule = models.CharField(max_length=10, choices=RULE_CHOICES)
    closed_with_difference = models.BooleanField(default=False)
    reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        constraints = [
            # Um par (lançamento, item) vincula uma única vez, mas um lançamento pode quitar
            # vários itens (remessa) e um item pode ser quitado por vários lançamentos (parcela).
            models.UniqueConstraint(fields=["transaction", "item"], name="uniq_link_pair"),
        ]

    def __str__(self) -> str:
        return f"{self.transaction_id} ↔ {self.item_id}"
