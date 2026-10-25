"""Testes da infra do Plano 2: models, services (motor), ingest e views.

Dados 100% sintéticos — nenhum dado real de cliente.
"""

from __future__ import annotations

from datetime import date

from accounts.models import Invite, Membership, Role, User
from conciliador_ui.templatetags.conciliador_ds import brl as brl_filter
from conciliador_ui.templatetags.conciliador_ds import doc as doc_filter
from django.test import TestCase

from . import models, services

_CNPJ_SEQ = [0]
_EMAIL_SEQ = [0]


def _company(name: str = "Oficina Exemplo Ltda", cnpj: str | None = None) -> models.Company:
    if cnpj is None:
        _CNPJ_SEQ[0] += 1
        cnpj = f"11{_CNPJ_SEQ[0]:012d}"
    return models.Company.objects.create(name=name, cnpj=cnpj)


def _user(company: models.Company, role: str = Role.OWNER, email: str | None = None) -> User:
    if email is None:
        _EMAIL_SEQ[0] += 1
        email = f"user{_EMAIL_SEQ[0]}@example.com"
    user = User.objects.create_user(email, "Dono Teste", "senha-forte-123")
    Membership.objects.create(user=user, company=company, role=role)
    return user


def _login(client, company: models.Company, role: str = Role.OWNER) -> User:
    user = _user(company, role)
    client.force_login(user)
    return user


def _account(company: models.Company) -> models.BankAccount:
    return models.BankAccount.objects.create(
        company=company, bank_id="0341", branch="1234", account_number="56789-0"
    )


def _tx(
    account: models.BankAccount,
    cents: int,
    memo: str,
    on: date,
    documents: list[str] | None = None,
    key: str = "k1",
) -> models.BankTransaction:
    return models.BankTransaction.objects.create(
        account=account,
        fitid="f1",
        posted_on=on,
        amount_cents=cents,
        memo=memo,
        documents=documents or [],
        dedup_key=key,
    )


def _item(
    company: models.Company,
    cents: int,
    due: date,
    direction: str = "inflow",
    counterpart_doc: str = "",
    number: str = "nº 1",
) -> models.ExpectedItem:
    return models.ExpectedItem.objects.create(
        company=company,
        external_id=f"nfe:{number}:1",
        source="nfe",
        direction=direction,
        amount_cents=cents,
        due_on=due,
        issued_on=due,
        counterpart_doc=counterpart_doc,
        counterpart_name="Cliente Alfa",
        document_number=number,
    )


class ReconcileTests(TestCase):
    def test_unmatched_becomes_bank_only_and_pending(self):
        company = _company()
        account = _account(company)
        _tx(account, 190000, "PIX RECEBIDO CLIENTE", date(2026, 1, 2), key="k-tx")
        _item(company, 50000, date(2026, 12, 1))  # vencimento futuro → pendente

        ctx = services.reconcile(company)
        statuses = {i["status"] for i in ctx["items"]}
        self.assertIn("nao_identificado", statuses)
        self.assertIn("pendente", statuses)
        self.assertEqual(ctx["counts"]["a_confirmar"], 0)

    def test_document_rule_matches_by_cnpj(self):
        company = _company()
        account = _account(company)
        _tx(
            account,
            190000,
            "PIX REC 45723174000110 ALFA",
            date(2026, 10, 21),
            documents=["45723174000110"],
            key="k-tx",
        )
        _item(company, 190000, date(2026, 10, 20), counterpart_doc="45723174000110")

        ctx = services.reconcile(company)
        self.assertEqual(ctx["counts"]["a_confirmar"], 1)
        item = next(i for i in ctx["items"] if i["status"] == "a_confirmar")
        self.assertEqual(item["rule"], "Regra 1")
        self.assertEqual(item["bank"]["cents"], 190000)

    def test_overdue_item(self):
        company = _company()
        _item(company, 98500, date(2024, 1, 15))  # vencimento passado → atrasado
        ctx = services.reconcile(company)
        self.assertTrue(any(i["status"] == "atrasado" for i in ctx["items"]))

    def test_confirm_creates_link(self):
        company = _company()
        account = _account(company)
        _tx(
            account,
            190000,
            "PIX REC 45723174000110 ALFA",
            date(2026, 10, 21),
            documents=["45723174000110"],
            key="k-tx",
        )
        _item(company, 190000, date(2026, 10, 20), counterpart_doc="45723174000110")

        before = services.reconcile(company)
        item = next(i for i in before["items"] if i["status"] == "a_confirmar")
        tx = models.BankTransaction.objects.get(pk=item["bank"]["id"])
        it = models.ExpectedItem.objects.get(pk=item["doc"]["id"])
        models.Link.objects.create(company=company, transaction=tx, item=it, rule="document")

        after = services.reconcile(company)
        self.assertTrue(any(i["status"] == "conciliado" for i in after["items"]))
        self.assertEqual(after["counts"]["a_confirmar"], 0)

    def test_confirmed_link_with_value_gap_is_divergence_with_facts(self):
        company = _company()
        account = _account(company)
        tx = _tx(account, -40840, "PAGTO BOLETO", date(2026, 10, 25), key="k-div")
        item = _item(company, 38990, date(2026, 10, 10), direction="outflow")
        models.Link.objects.create(company=company, transaction=tx, item=item, rule="document")

        ctx = services.reconcile(company, account)
        div = next(i for i in ctx["items"] if i["status"] == "divergencia")
        self.assertEqual(div["direction"], "out")
        self.assertIn("15 dias após o vencimento", div["facts"])
        self.assertIn("a mais", div["diff_title"])
        self.assertIn("a mais que o documento", div["diff_reason"])

    def test_confirmed_link_on_due_date_has_no_value_gap(self):
        company = _company()
        account = _account(company)
        tx = _tx(account, 190000, "PIX", date(2026, 10, 20), key="k-ok")
        item = _item(company, 190000, date(2026, 10, 20))
        models.Link.objects.create(company=company, transaction=tx, item=item, rule="document")

        ctx = services.reconcile(company, account)
        ok = next(i for i in ctx["items"] if i["status"] == "conciliado")
        self.assertEqual(ok["facts"], ["vínculo confirmado", "no dia do vencimento"])
        self.assertNotIn("diff_title", ok)


class AccountAndBalanceTests(TestCase):
    def test_reconcile_filters_by_account(self):
        company = _company()
        a1 = _account(company)
        a2 = models.BankAccount.objects.create(
            company=company, bank_id="001", branch="0001", account_number="22222-2"
        )
        _tx(a1, 100000, "PIX A", date(2026, 1, 1), key="k-a")
        _tx(a2, -50000, "PIX B", date(2026, 1, 2), key="k-b")

        ctx = services.reconcile(company, a1)
        memos = [i["bank"]["memo"] for i in ctx["items"] if i.get("bank")]
        self.assertEqual(memos, ["PIX A"])

    def test_balance_unknown_opening_does_not_claim_it_closes(self):
        company = _company()
        account = _account(company)
        account.ledger_balance_cents = 38000
        account.save()
        _tx(account, 50000, "PIX", date(2026, 1, 1), key="k1")
        _tx(account, -12000, "BOLETO", date(2026, 1, 2), key="k2")

        balance = services.reconcile(company, account)["balance"]
        self.assertIsNone(balance["opening"])
        self.assertIsNone(balance["statement_consistent"])
        self.assertFalse(balance["balanced"])
        self.assertEqual(balance["unexplained"], 38000)

    def test_statement_closes_when_opening_is_known(self):
        company = _company()
        account = _account(company)
        account.ledger_balance_cents = 38000
        account.opening_balance_cents = 0
        account.save()
        _tx(account, 50000, "PIX", date(2026, 1, 1), key="k1")
        _tx(account, -12000, "BOLETO", date(2026, 1, 2), key="k2")

        balance = services.reconcile(company, account)["balance"]
        self.assertTrue(balance["statement_consistent"])

    def test_balance_balances_only_when_everything_is_explained(self):
        company = _company()
        account = _account(company)
        account.ledger_balance_cents = 38000
        account.opening_balance_cents = 0
        account.save()
        tx_in = _tx(
            account,
            50000,
            "PIX REC 45723174000110",
            date(2026, 1, 1),
            documents=["45723174000110"],
            key="k1",
        )
        tx_out = _tx(
            account,
            -12000,
            "PAGTO 45723174000110",
            date(2026, 1, 2),
            documents=["45723174000110"],
            key="k2",
        )
        item_in = _item(
            company, 50000, date(2026, 1, 1), counterpart_doc="45723174000110", number="nº 1"
        )
        item_out = _item(
            company,
            12000,
            date(2026, 1, 2),
            direction="outflow",
            counterpart_doc="45723174000110",
            number="nº 2",
        )
        models.Link.objects.create(
            company=company, transaction=tx_in, item=item_in, rule="document"
        )
        models.Link.objects.create(
            company=company, transaction=tx_out, item=item_out, rule="document"
        )

        balance = services.reconcile(company, account)["balance"]
        self.assertTrue(balance["balanced"])
        self.assertEqual(balance["difference"], 0)

    def test_unexplained_keeps_balance_open(self):
        company = _company()
        account = _account(company)
        account.ledger_balance_cents = 0
        account.opening_balance_cents = 0
        account.save()
        _tx(account, 50000, "PIX SEM DOC", date(2026, 1, 1), key="k1")

        balance = services.reconcile(company, account)["balance"]
        self.assertFalse(balance["balanced"])
        self.assertEqual(balance["unexplained"], 50000)
        self.assertEqual(balance["difference"], -50000)


class ReconciliationFeatureTests(TestCase):
    def test_classify_bank_only_removes_it_from_unexplained(self):
        company = _company()
        account = _account(company)
        _login(self.client, company)
        account.ledger_balance_cents = -3990
        account.opening_balance_cents = 0
        account.save()
        _tx(account, -3990, "TARIFA PACOTE", date(2026, 1, 1), key="k1")

        before = services.reconcile(company, account)
        self.assertEqual(before["balance"]["unexplained"], -3990)
        item = next(i for i in before["items"] if i["status"] == "nao_identificado")

        self.client.post(
            f"/item/{item['id']}/classificar/",
            {"kind": "tarifa", "note": "pacote mensal"},
        )
        after = services.reconcile(company, account)
        self.assertEqual(after["balance"]["unexplained"], 0)
        self.assertTrue(after["balance"]["balanced"])
        statuses = {i["status"] for i in after["items"]}
        self.assertIn("classificado", statuses)
        self.assertNotIn("nao_identificado", statuses)

    def test_transfer_is_neutral_and_does_not_count_twice(self):
        company = _company()
        _login(self.client, company)
        a1 = _account(company)
        a2 = models.BankAccount.objects.create(
            company=company, bank_id="001", branch="0001", account_number="99999-9"
        )
        _tx(a1, -50000, "TRANSF PARA CONTA 2", date(2026, 1, 1), key="k-deb")
        _tx(a2, 50000, "TRANSF DA CONTA 1", date(2026, 1, 1), key="k-cred")

        ctx = services.reconcile(company, a1)
        deb = next(
            i for i in ctx["items"] if i["bank"] and i["bank"]["memo"] == "TRANSF PARA CONTA 2"
        )
        self.client.post(
            f"/item/{deb['id']}/classificar/",
            {
                "kind": "transferencia",
                "counterpart": str(models.BankTransaction.objects.get(dedup_key="k-cred").pk),
            },
        )
        after = services.reconcile(company, a1)
        self.assertEqual(after["balance"]["unexplained"], 0)
        statuses = {i["status"] for i in after["items"]}
        self.assertIn("transferencia", statuses)

    def test_partial_suggestion_and_confirm(self):
        company = _company()
        account = _account(company)
        _login(self.client, company)
        _tx(
            account,
            40000,
            "PIX 45723174000110",
            date(2026, 10, 20),
            documents=["45723174000110"],
            key="k1",
        )
        _tx(
            account,
            60000,
            "PIX 45723174000110",
            date(2026, 10, 21),
            documents=["45723174000110"],
            key="k2",
        )
        _item(company, 100000, date(2026, 10, 20), counterpart_doc="45723174000110")

        ctx = services.reconcile(company, account)
        partial = next(i for i in ctx["items"] if i.get("kind") == "partial")
        self.assertEqual(partial["status"], "a_confirmar")
        self.assertEqual(len(partial["bank_many"]), 2)

        self.client.post(f"/item/{partial['id']}/confirmar/")
        self.assertEqual(models.Link.objects.count(), 2)
        after = services.reconcile(company, account)
        self.assertTrue(after["balance"]["balanced"])

    def test_batch_suggestion_and_confirm(self):
        company = _company()
        account = _account(company)
        _login(self.client, company)
        _tx(
            account,
            100000,
            "PIX 45723174000110",
            date(2026, 10, 20),
            documents=["45723174000110"],
            key="k1",
        )
        _item(company, 40000, date(2026, 10, 20), counterpart_doc="45723174000110", number="a")
        _item(company, 60000, date(2026, 10, 20), counterpart_doc="45723174000110", number="b")

        ctx = services.reconcile(company, account)
        batch = next(i for i in ctx["items"] if i.get("kind") == "batch")
        self.assertEqual(len(batch["doc_many"]), 2)

        self.client.post(f"/item/{batch['id']}/confirmar/")
        self.assertEqual(models.Link.objects.count(), 2)
        self.assertTrue(services.reconcile(company, account)["balance"]["balanced"])

    def test_aprovar_lote_confirms_high_confidence_only(self):
        company = _company()
        account = _account(company)
        _login(self.client, company)
        _tx(
            account,
            190000,
            "PIX 45723174000110",
            date(2026, 10, 20),
            documents=["45723174000110"],
            key="k1",
        )
        _item(company, 190000, date(2026, 10, 20), counterpart_doc="45723174000110", number="a")

        ctx = services.reconcile(company, account)
        self.assertEqual(ctx["counts"]["a_confirmar"], 1)
        self.assertEqual(ctx["counts"]["a_confirmar_lote"], 1)

        self.client.post(f"/aprovar-lote/?conta={account.pk}")
        self.assertEqual(models.Link.objects.count(), 1)
        self.assertTrue(services.reconcile(company, account)["balance"]["balanced"])


class FilterTests(TestCase):
    def test_brl_formats_cents(self):
        html = str(brl_filter(-1990))
        self.assertIn("\u2212", html)
        self.assertIn("R$", html)
        self.assertIn("19", html)
        self.assertIn(",90", html)
        pos = str(brl_filter(190000, "always"))
        self.assertIn("+", pos)
        self.assertIn("amount--in", pos)
        self.assertIn("1.900", pos)
        never = str(brl_filter(4321010, "never"))
        self.assertNotIn("\u2212", never)
        self.assertIn("43.210", never)

    def test_doc_masks_cpf_and_formats_cnpj(self):
        self.assertIn("***.982.247-**", str(doc_filter("52998224725")))
        self.assertIn("CPF", str(doc_filter("52998224725")))
        self.assertIn("12.345.678/0001-95", str(doc_filter("12345678000195")))
        self.assertIn("CNPJ", str(doc_filter("12345678000195")))


class ViewTests(TestCase):
    def setUp(self):
        self.company = _company()
        self.account = _account(self.company)
        _login(self.client, self.company)
        _tx(self.account, 100000, "RECEBIMENTO CLIENTE FICTICIO", date(2026, 1, 1), key="k1")
        _tx(self.account, -20000, "ALUGUEL DEMONSTRACAO", date(2026, 1, 2), key="k2")
        _item(self.company, 98500, date(2024, 1, 15))

    def test_fechamento_renders(self):
        self.assertEqual(self.client.get("/fechamento/atual/").status_code, 200)

    def test_contador_renders_read_only(self):
        from django.test import Client

        c = Client()
        _login(c, self.company, Role.ACCOUNTANT)
        html = c.get("/fechamento/atual/").content.decode()
        self.assertEqual(c.get("/fechamento/atual/").status_code, 200)
        self.assertIn("Demonstrativo de conciliação", html)
        self.assertIn("somente leitura", html)

    def test_contador_cannot_mutate(self):
        from django.test import Client

        c = Client()
        _login(c, self.company, Role.ACCOUNTANT)
        # qualquer POST de mutação devolve 403
        item = next(
            i
            for i in services.reconcile(self.company)["items"]
            if i["status"] == "nao_identificado" and i.get("bank")
        )
        resp = c.post(f"/item/{item['id']}/classificar/", {"kind": "tarifa"})
        self.assertEqual(resp.status_code, 403)

    def test_anonymous_is_redirected_to_login(self):
        from django.test import Client

        resp = Client().get("/fechamento/atual/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/entrar/", resp["Location"])

    def test_landing_renders(self):
        self.assertEqual(self.client.get("/landing/").status_code, 200)

    def test_importacao_renders(self):
        self.assertEqual(self.client.get("/importacao/").status_code, 200)

    def test_detalhe_renders(self):
        tx = models.BankTransaction.objects.first()
        self.assertEqual(self.client.get(f"/item/tx:{tx.pk}/").status_code, 200)

    def test_account_param_filters_the_list(self):
        other = models.BankAccount.objects.create(
            company=self.company, bank_id="001", branch="0001", account_number="99999-9"
        )
        _tx(other, -7777, "SO NA CONTA DOIS", date(2026, 1, 3), key="k-outra")
        html = self.client.get(f"/fechamento/atual/?conta={other.pk}").content.decode()
        self.assertIn("SO NA CONTA DOIS", html)
        self.assertNotIn("RECEBIMENTO CLIENTE FICTICIO", html)

    def test_primary_account_opens_by_default(self):
        other = models.BankAccount.objects.create(
            company=self.company,
            bank_id="001",
            branch="0001",
            account_number="88888-8",
            is_primary=True,
        )
        _tx(other, -5555, "CONTA PRINCIPAL", date(2026, 1, 4), key="k-principal")
        html = self.client.get("/fechamento/atual/").content.decode()
        self.assertIn("CONTA PRINCIPAL", html)
        self.assertNotIn("RECEBIMENTO CLIENTE FICTICIO", html)

    def test_confirm_endpoint(self):
        _tx(
            self.account,
            190000,
            "PIX REC 45723174000110 ALFA",
            date(2026, 10, 21),
            documents=["45723174000110"],
            key="k3",
        )
        _item(
            self.company,
            190000,
            date(2026, 10, 20),
            counterpart_doc="45723174000110",
            number="nº 2",
        )
        item = next(
            i for i in services.reconcile(self.company)["items"] if i["status"] == "a_confirmar"
        )
        resp = self.client.post(f"/item/{item['id']}/confirmar/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(models.Link.objects.count(), 1)


class IngestTests(TestCase):
    def test_ingest_synthetic_ofx(self):
        from conciliador_synth.ofx import SynthTxn, make_ofx

        company = _company()
        import tempfile
        from pathlib import Path

        from .ingest import ingest_ofx

        data = make_ofx(
            [
                SynthTxn(date(2026, 1, 5), 50000, "PIX RECEBIDO TESTE", fitid="t1"),
                SynthTxn(date(2026, 1, 6), -12000, "PAGTO BOLETO", fitid="t2"),
            ],
            ledger_balance_cents=38000,
        )
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "synth.ofx"
            path.write_bytes(data)
            report = ingest_ofx(data, path.name, company)
        self.assertTrue(report["ok"])
        self.assertEqual(report["txns"], 2)
        self.assertEqual(models.BankTransaction.objects.count(), 2)

    def test_ingest_csv_items(self):
        import tempfile
        from pathlib import Path

        from .ingest import ingest_csv

        company = _company()
        csv = (
            "tipo;valor;vencimento;contraparte_nome;contraparte_documento;"
            "documento_numero;descricao\n"
            "pagar;250,90;10/11/2026;Fornecedor Exemplo SA;12.345.678/0001-95;2002;Compra\n"
            "receber;1.500,00;05/11/2026;Cliente Exemplo Ltda;45.723.174/0001-10;1001;Venda\n"
        )
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "contas.csv"
            path.write_text(csv, encoding="utf-8")
            report = ingest_csv(csv.encode("utf-8"), path.name, company)
        self.assertTrue(report["ok"])
        self.assertEqual(report["items"], 2)
        self.assertEqual(models.ExpectedItem.objects.filter(direction="outflow").count(), 1)
        self.assertEqual(models.ExpectedItem.objects.filter(direction="inflow").count(), 1)


class HealthTests(TestCase):
    def test_health_returns_ok(self):
        for url in ("/health", "/health/"):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json(), {"status": "ok"})


class UploadTests(TestCase):
    def setUp(self):
        self.company = _company()
        _login(self.client, self.company)

    def _upload(self, kind, name, content):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return self.client.post(
            f"/importacao/enviar/{kind}/",
            {"files": SimpleUploadedFile(name, content)},
        )

    def test_upload_ofx_ingests_transactions(self):
        from conciliador_synth.ofx import SynthTxn, make_ofx

        data = make_ofx(
            [SynthTxn(date(2026, 1, 5), 50000, "PIX RECEBIDO", fitid="t1")],
            ledger_balance_cents=50000,
        )
        resp = self._upload("ofx", "extrato.ofx", data)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("1 lançamento", resp.content.decode())
        self.assertEqual(models.BankTransaction.objects.count(), 1)
        job = models.ImportJob.objects.get()
        self.assertEqual(job.state, "done")

    def test_upload_csv_ingests_items(self):
        csv = (
            b"tipo;valor;vencimento;contraparte_nome;contraparte_documento;"
            b"documento_numero;descricao\n"
            b"pagar;250,90;10/11/2026;Fornecedor Exemplo SA;12.345.678/0001-95;2002;Compra\n"
        )
        resp = self._upload("csv", "contas.csv", csv)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(models.ExpectedItem.objects.filter(direction="outflow").count(), 1)

    def test_upload_invalid_file_is_error(self):
        resp = self._upload("ofx", "ruim.ofx", b"isso nao e ofx")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("dropzone--error", resp.content.decode())
        self.assertEqual(models.ImportJob.objects.get().state, "error")

    def test_contador_cannot_upload(self):
        from django.test import Client

        c = Client()
        _login(c, self.company, Role.ACCOUNTANT)
        resp = c.post("/importacao/enviar/ofx/", {})
        self.assertEqual(resp.status_code, 403)


class AccountsTests(TestCase):
    def test_signup_creates_company_and_owner(self):
        resp = self.client.post(
            "/comecar/",
            {"email": "nova@example.com", "name": "Nova Empresa", "password": "senha-forte-123"},
        )
        self.assertEqual(resp.status_code, 302)
        user = User.objects.get(email="nova@example.com")
        self.assertTrue(Membership.objects.filter(user=user, role=Role.OWNER).exists())
        self.assertTrue(user.is_authenticated)

    def test_login_wrong_password_is_rejected(self):
        company = _company()
        user = _user(company)
        resp = self.client.post("/entrar/", {"email": user.email, "password": "errada"})
        self.assertEqual(resp.status_code, 401)

    def test_login_with_mfa_requires_code(self):
        import pyotp

        company = _company()
        user = _user(company)
        secret = pyotp.random_base32()
        user.mfa_secret = secret
        user.save(update_fields=["mfa_secret"])

        resp = self.client.post("/entrar/", {"email": user.email, "password": "senha-forte-123"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/entrar/mfa/", resp["Location"])

        wrong = self.client.post("/entrar/mfa/", {"code": "000000"})
        self.assertEqual(wrong.status_code, 401)

        right = self.client.post("/entrar/mfa/", {"code": pyotp.TOTP(secret).now()})
        self.assertEqual(right.status_code, 302)

    def test_invite_flow_grants_accountant_access(self):
        from django.test import Client

        owner_company = _company()
        owner = _user(owner_company)
        self.client.force_login(owner)
        self.client.post("/convites/", {"email": "contador@example.com"})
        invite = Invite.objects.get(email="contador@example.com")

        c = Client()
        resp = c.get(f"/entrar-convite/{invite.token}/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/comecar/", resp["Location"])

        c.post(
            "/comecar/",
            {"email": "contador@example.com", "name": "Contador", "password": "senha-forte-123"},
        )
        contador = User.objects.get(email="contador@example.com")
        self.assertTrue(
            Membership.objects.filter(
                user=contador, company=owner_company, role=Role.ACCOUNTANT
            ).exists()
        )

    def test_company_isolation_between_owners(self):
        from django.test import Client

        a = _company()
        _tx(_account(a), 12345, "PIX DA EMPRESA A", date(2026, 1, 1), key="k-a")
        b = _company()
        _tx(_account(b), 99999, "PIX DA EMPRESA B", date(2026, 1, 1), key="k-b")

        ca = Client()
        _login(ca, a)
        html = ca.get("/fechamento/atual/").content.decode()
        self.assertIn("PIX DA EMPRESA A", html)
        self.assertNotIn("PIX DA EMPRESA B", html)
