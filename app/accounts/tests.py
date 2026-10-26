"""Testes de identidade: checagem de CNPJ (dígito + Receita) e tela Empresa."""

from __future__ import annotations

import urllib.error
from unittest import mock

from django.test import Client, TestCase
from ledger.models import AuditLog, Company

from .cnpj import check_cnpj
from .models import Membership, Role, User

_SENHA = "senha-forte-123"  # fictícia, só para testes

VALID = "11222333000181"


def _company(cnpj: str = "00000000000001") -> Company:
    return Company.objects.create(name="Oficina Exemplo", cnpj=cnpj)


def _owner(client: Client, company: Company) -> User:
    import pyotp

    user = User.objects.create_user("dono@ex.com", "Dono", _SENHA)
    user.mfa_secret = pyotp.random_base32()
    user.save(update_fields=["mfa_secret"])
    Membership.objects.create(user=user, company=company, role=Role.OWNER)
    client.force_login(user)
    return user


class CnpjCheckTests(TestCase):
    def test_invalid_digit_is_rejected_locally(self):
        check = check_cnpj("11222333000182")
        self.assertFalse(check.valid_dv)
        self.assertIn("dígito", check.error)

    @mock.patch(
        "accounts.cnpj._fetch",
        return_value=(
            200,
            {
                "razao_social": "Empresa Teste Ltda",
                "situacao_cadastral": 1,
                "descricao_situacao_cadastral": "Ativa",
            },
        ),
    )
    def test_active_cnpj_is_found(self, _fetch):
        check = check_cnpj(VALID)
        self.assertTrue(check.found)
        self.assertTrue(check.active)
        self.assertEqual(check.razao_social, "Empresa Teste Ltda")

    @mock.patch(
        "accounts.cnpj._fetch", side_effect=urllib.error.HTTPError("u", 404, "nf", {}, None)
    )
    def test_not_found_is_reported(self, _fetch):
        check = check_cnpj(VALID)
        self.assertFalse(check.found)

    @mock.patch("accounts.cnpj._fetch", side_effect=urllib.error.URLError("offline"))
    def test_network_error_does_not_block(self, _fetch):
        check = check_cnpj(VALID)
        self.assertTrue(check.valid_dv)
        self.assertIsNone(check.found)

    @mock.patch("accounts.cnpj._fetch", side_effect=ValueError("json inválido"))
    def test_invalid_response_does_not_block(self, _fetch):
        check = check_cnpj(VALID)
        self.assertTrue(check.valid_dv)
        self.assertIsNone(check.found)


class EmpresaViewTests(TestCase):
    def setUp(self):
        self.company = _company()
        _owner(self.client, self.company)

    @mock.patch(
        "accounts.cnpj._fetch",
        return_value=(
            200,
            {
                "razao_social": "Empresa Teste Ltda",
                "situacao_cadastral": 1,
                "descricao_situacao_cadastral": "Ativa",
            },
        ),
    )
    def test_saves_verified_cnpj(self, _fetch):
        resp = self.client.post("/empresa/", {"name": "Nova Empresa", "cnpj": "11.222.333/0001-81"})
        self.assertEqual(resp.status_code, 302)
        self.company.refresh_from_db()
        self.assertEqual(self.company.cnpj, VALID)
        self.assertTrue(self.company.cnpj_verified)
        self.assertEqual(self.company.name, "Nova Empresa")

    def test_rejects_invalid_cnpj(self):
        resp = self.client.post("/empresa/", {"name": "Nova", "cnpj": "11.222.333/0001-82"})
        self.assertEqual(resp.status_code, 400)

    @mock.patch(
        "accounts.cnpj._fetch",
        return_value=(
            200,
            {
                "razao_social": "X",
                "situacao_cadastral": 8,
                "descricao_situacao_cadastral": "Baixada",
            },
        ),
    )
    def test_rejects_inactive_cnpj(self, _fetch):
        resp = self.client.post("/empresa/", {"name": "Nova", "cnpj": VALID})
        self.assertEqual(resp.status_code, 400)
        self.company.refresh_from_db()
        self.assertFalse(self.company.cnpj_verified)

    @mock.patch(
        "accounts.cnpj._fetch",
        return_value=(
            200,
            {
                "razao_social": "Empresa Teste Ltda",
                "situacao_cadastral": 1,
                "descricao_situacao_cadastral": "Ativa",
            },
        ),
    )
    def test_rejects_cnpj_from_another_company(self, _fetch):
        _company(cnpj=VALID)
        resp = self.client.post("/empresa/", {"name": "Nova", "cnpj": VALID})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("já está cadastrado", resp.content.decode())
        self.company.refresh_from_db()
        self.assertNotEqual(self.company.cnpj, VALID)

    def test_accountant_cannot_edit(self):
        import pyotp

        c = Client()
        company2 = _company(cnpj="00000000000002")
        user = User.objects.create_user("cont@ex.com", "Cont", _SENHA)
        user.mfa_secret = pyotp.random_base32()
        user.save(update_fields=["mfa_secret"])
        Membership.objects.create(user=user, company=company2, role=Role.ACCOUNTANT)
        c.force_login(user)
        resp = c.get("/empresa/")
        self.assertEqual(resp.status_code, 403)


class SemEmpresaTests(TestCase):
    """Deploy vazio: o superusuário sem empresa cadastra a primeira antes de usar o painel."""

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        import pyotp

        self.user = User.objects.create_superuser("admin@ex.com", "Admin", _SENHA)
        self.user.mfa_secret = pyotp.random_base32()
        self.user.save(update_fields=["mfa_secret"])
        self.client.force_login(self.user)

    def test_painel_redireciona_para_cadastro_da_empresa(self):
        resp = self.client.get("/fechamento/atual/")

        self.assertRedirects(resp, "/empresa/")

    def test_pagina_de_empresa_abre_em_modo_de_cadastro(self):
        resp = self.client.get("/empresa/")

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Cadastre sua empresa")

    @mock.patch(
        "accounts.cnpj._fetch",
        return_value=(
            200,
            {
                "razao_social": "Empresa Teste Ltda",
                "situacao_cadastral": 1,
                "descricao_situacao_cadastral": "Ativa",
            },
        ),
    )
    def test_cria_primeira_empresa_e_entra_no_painel(self, _fetch):
        resp = self.client.post("/empresa/", {"name": "Minha Empresa", "cnpj": VALID})

        self.assertEqual(resp.status_code, 302)
        company = Company.objects.get(cnpj=VALID)
        self.assertTrue(
            Membership.objects.filter(user=self.user, company=company, role=Role.OWNER).exists()
        )
        self.assertTrue(AuditLog.objects.filter(action="company_created", company=company).exists())
        self.assertEqual(self.client.get("/fechamento/atual/").status_code, 200)

    def test_sem_mfa_nao_cadastra_antes_de_ativar(self):
        user = User.objects.create_user("sem-mfa@ex.com", "Sem MFA", _SENHA)
        self.client.force_login(user)

        resp = self.client.get("/empresa/")

        self.assertRedirects(resp, "/seguranca/mfa/")
