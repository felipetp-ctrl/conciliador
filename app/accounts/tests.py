"""Testes de identidade: checagem de CNPJ (dígito + Receita) e tela Empresa."""

from __future__ import annotations

import urllib.error
from unittest import mock

from django.test import Client, TestCase
from ledger.models import Company

from .cnpj import check_cnpj
from .models import Membership, Role, User

VALID = "11222333000181"


def _company(cnpj: str = "00000000000001") -> Company:
    return Company.objects.create(name="Oficina Exemplo", cnpj=cnpj)


def _owner(client: Client, company: Company) -> User:
    user = User.objects.create_user("dono@ex.com", "Dono", "senha-forte-123")
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
        c = Client()
        company2 = _company(cnpj="00000000000002")
        user = User.objects.create_user("cont@ex.com", "Cont", "senha-forte-123")
        Membership.objects.create(user=user, company=company2, role=Role.ACCOUNTANT)
        c.force_login(user)
        resp = c.get("/empresa/")
        self.assertEqual(resp.status_code, 403)
