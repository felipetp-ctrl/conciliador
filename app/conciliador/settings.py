"""Configuração do Django — conciliador (Plano 2).

Front renderizado no servidor com HTMX, sem SPA. Persistência em SQLite (local);
autenticação e multi-tenant entram nas próximas tarefas. ``SECRET_KEY`` vem do
ambiente (com um fallback de desenvolvimento — nunca usar em produção).
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-key")
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "accounts.apps.AccountsConfig",
    "conciliador_ui",
    "ledger.apps.LedgerConfig",
]

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]

AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "fechamento"
LOGOUT_REDIRECT_URL = "login"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

ROOT_URLCONF = "conciliador.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.csrf",
                "django.template.context_processors.static",
                "django.contrib.auth.context_processors.auth",
                "conciliador.context_processors.globals",
            ],
        },
    },
]

WSGI_APPLICATION = "conciliador.wsgi.application"
ASGI_APPLICATION = "conciliador.asgi.application"

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
