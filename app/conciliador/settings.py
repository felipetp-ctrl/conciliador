"""Configuração do Django — conciliador (Plano 2).

Front renderizado no servidor com HTMX, sem SPA. Em desenvolvimento a persistência é
SQLite; no deploy, PostgreSQL via ``DATABASE_URL``. ``SECRET_KEY`` e ``DEBUG`` vêm do
ambiente (o fallback de desenvolvimento nunca deve ser usado em produção).
"""

import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, "1" if default else "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _env_list(name: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


def _database_from_url(url: str) -> dict:
    """Converte ``postgres://user:senha@host:porta/banco?sslmode=require`` em DATABASES."""
    parsed = urlparse(url)
    if parsed.scheme not in ("postgres", "postgresql"):
        raise ValueError("DATABASE_URL deve começar com postgres:// ou postgresql://")
    query = parse_qs(parsed.query)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed.path.lstrip("/")),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or ""),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {
            "sslmode": query.get("sslmode", [os.environ.get("DATABASE_SSLMODE", "prefer")])[0]
        },
    }


SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-key")
DEBUG = _env_bool("DEBUG", True)

ALLOWED_HOSTS = _env_list("ALLOWED_HOSTS") or (["*"] if DEBUG else [])
CSRF_TRUSTED_ORIGINS = _env_list("CSRF_TRUSTED_ORIGINS")

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
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

if not DEBUG:
    # WhiteNoise serve os estáticos coletados sem um servidor separado.
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "fechamento"
LOGOUT_REDIRECT_URL = "login"

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
DATABASES = {
    "default": (
        _database_from_url(DATABASE_URL)
        if DATABASE_URL
        else {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    )
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
STATIC_ROOT = BASE_DIR / "staticfiles"

if not DEBUG:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------- #
# Produção (deploy): HTTPS atrás do proxy e cabeçalhos de segurança.
# --------------------------------------------------------------------------- #
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True
    SECURE_SSL_REDIRECT = _env_bool("SECURE_SSL_REDIRECT", False)
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", True)
    CSRF_COOKIE_SECURE = _env_bool("CSRF_COOKIE_SECURE", True)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "3600"))
    if SECURE_HSTS_SECONDS:
        SECURE_HSTS_INCLUDE_SUBDOMAINS = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {
        "handlers": ["console"],
        "level": os.environ.get("LOG_LEVEL", "INFO"),
    },
}
