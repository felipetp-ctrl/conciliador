"""Modelos de identidade e tenancy: usuário, membro de empresa e convite.

- ``User``: e-mail como identificador (com TOTP opcional para MFA).
- ``Membership``: liga um usuário a uma ``ledger.Company`` com papel dono ou contador.
- ``Invite``: convite por link/token para um contador entrar numa empresa (somente leitura).
"""

from __future__ import annotations

import secrets

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.db import models
from ledger.models import Company


class UserManager(BaseUserManager):
    def create_user(self, email: str, name: str, password: str | None = None) -> User:
        user = self.model(email=self.normalize_email(email).lower(), name=name.strip())
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, name: str, password: str) -> User:
        user = self.create_user(email, name, password)
        user.is_staff = True
        user.save(using=self._db, update_fields=["is_staff"])
        return user


class User(AbstractBaseUser):
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=200)
    # seed TOTP em base32; vazio = MFA desabilitado.
    mfa_secret = models.CharField(max_length=32, blank=True, default="")
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    objects = UserManager()

    def get_full_name(self) -> str:
        return self.name

    def get_short_name(self) -> str:
        return self.name.split()[0] if self.name else self.email

    def has_perm(self, perm, obj=None) -> bool:  # noqa: ANN001, ARG002
        return self.is_staff

    def has_module_perms(self, app_label: str) -> bool:
        return self.is_staff

    def __str__(self) -> str:
        return self.email


class Role(models.TextChoices):
    OWNER = "owner", "dono"
    ACCOUNTANT = "accountant", "contador"


class Membership(models.Model):
    """Um usuário numa empresa, com um papel. O dono edita; o contador só lê."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=20, choices=Role.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "company"], name="uniq_membership"),
        ]

    def __str__(self) -> str:
        return f"{self.user.email} @ {self.company.name} ({self.role})"


class Invite(models.Model):
    """Convite pendente de contador. O token vira o link ``/entrar-convite/<token>/``."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="invites")
    email = models.EmailField()
    token = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    accepted = models.BooleanField(default=False)

    @classmethod
    def new_token(cls) -> str:
        return secrets.token_urlsafe(32)

    def __str__(self) -> str:
        return f"{self.email} → {self.company.name}"


def seed_demo_user(
    company: Company,
    email: str = "demo@conciliador.local",
    # senha de demonstração local; nunca é usada em produção
    password: str = "demo12345",  # noqa: S107  # nosec B107
) -> User:
    """Usuário dono de demonstração (só para desenvolvimento local)."""
    user, created = User.objects.get_or_create(email=email, defaults={"name": "Demonstração"})
    if created:
        user.set_password(password)
        user.save(update_fields=["password"])
    Membership.objects.get_or_create(user=user, company=company, defaults={"role": Role.OWNER})
    return user
