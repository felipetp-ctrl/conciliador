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


SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()
DEBUG = _env_bool("DEBUG", True)
if not SECRET_KEY:
    if DEBUG:
        # chave insegura só para desenvolvimento; produção exige SECRET_KEY no ambiente
        SECRET_KEY = "dev-only-insecure-key"  # nosec B105
    else:
        raise RuntimeError("Defina SECRET_KEY no ambiente quando DEBUG=0.")

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
    "conciliador.middleware.ContentSecurityPolicyMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "conciliador.middleware.MFAEnrollmentMiddleware",
    "conciliador.middleware.CompanySetupMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

if not DEBUG:
    # WhiteNoise serve os estáticos coletados sem um servidor separado.
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

AUTH_USER_MODEL = "accounts.User"

# Argon2 é o primeiro; os demais mantêm compatibilidade com hashes antigos.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

# Sessão expira por inatividade (cada requisição renova o prazo).
SESSION_COOKIE_AGE = int(os.environ.get("SESSION_COOKIE_AGE", str(8 * 60 * 60)))
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# Cache do limite de tentativas. O piloto roda com um worker; com mais de um
# processo, troque por um cache compartilhado (Redis ou banco) para o limite valer.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "conciliador",
    }
}

# Contato exibido nas páginas de privacidade e termos (definir no deploy).
LEGAL_CONTACT_EMAIL = os.environ.get("LEGAL_CONTACT_EMAIL", "").strip()

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "fechamento"
LOGOUT_REDIRECT_URL = "login"

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
SQLITE_PATH = os.environ.get("SQLITE_PATH", "").strip()


def _sqlite_name() -> Path:
    """Arquivo do SQLite: ``/home/data/...`` no App Service, ``app/db.sqlite3`` local."""
    return Path(SQLITE_PATH) if SQLITE_PATH else BASE_DIR / "db.sqlite3"


DATABASES = {
    "default": (
        _database_from_url(DATABASE_URL)
        if DATABASE_URL
        else {
            "ENGINE": "django.db.backends.sqlite3",
            # No piloto do App Service o arquivo fica em /home/data (persistente e
            # fora do wwwroot, que é substituído a cada deploy).
            "NAME": _sqlite_name(),
            "OPTIONS": {"timeout": 20},
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
STATIC_ROOT = Path(os.environ.get("STATIC_ROOT", "").strip() or (BASE_DIR / "staticfiles"))

# Uploads: o arquivo é gravado em disco acima deste tamanho e o app recusa antes de ler
# (o limite fino por formato fica em ``conciliador_core.parsers._limits``).
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_BYTES
FILE_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_BYTES
DATA_UPLOAD_MAX_NUMBER_FILES = 20

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
