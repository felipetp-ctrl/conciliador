#!/usr/bin/env bash
# Azure App Service (Linux, Python) — inicialização do conciliador.
# App Service › Configuration › Startup Command:  bash deploy/startup.sh
#
# O piloto usa SQLite em /home/data (persistente, fora do wwwroot). Para migrar
# para PostgreSQL basta definir DATABASE_URL e remover SQLITE_PATH; o script não
# muda.
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON_BIN:-python}"
command -v "$PYTHON" >/dev/null 2>&1 || PYTHON=python3
VENV="${VENV_PATH:-/home/venv}"

if [ ! -x "$VENV/bin/python" ]; then
  echo "criando venv em $VENV"
  "$PYTHON" -m venv "$VENV"
fi

req_hash() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

HASH="$(req_hash deploy/requirements.txt)"
if [ "$(cat "$VENV/.req-hash" 2>/dev/null || true)" != "$HASH" ]; then
  echo "instalando dependências"
  "$VENV/bin/python" -m pip install --upgrade pip
  "$VENV/bin/python" -m pip install --disable-pip-version-check -r deploy/requirements.txt
  printf '%s\n' "$HASH" > "$VENV/.req-hash"
fi

# Backup do SQLite antes de migrar: o app ainda não está rodando, então a cópia
# é consistente. Mantém os 7 últimos arquivos em /home/backups.
if [ -n "${SQLITE_PATH:-}" ]; then
  BACKUP_DIR="${BACKUP_DIR:-/home/backups}"
  mkdir -p "$(dirname "$SQLITE_PATH")" "$BACKUP_DIR"
  if [ -f "$SQLITE_PATH" ]; then
    cp "$SQLITE_PATH" "$BACKUP_DIR/conciliador-$(date +%Y%m%d-%H%M%S).sqlite3"
    ls -1t "$BACKUP_DIR"/conciliador-*.sqlite3 2>/dev/null | tail -n +8 | while read -r old; do
      rm -f "$old"
    done
  fi
fi

if [ -n "${STATIC_ROOT:-}" ]; then
  mkdir -p "$STATIC_ROOT"
fi

"$VENV/bin/python" app/manage.py migrate --noinput
"$VENV/bin/python" app/manage.py collectstatic --noinput

WORKERS="${WEB_CONCURRENCY:-2}"
if [ -n "${SQLITE_PATH:-}" ] && [ -z "${WEB_CONCURRENCY:-}" ]; then
  WORKERS=1
fi

exec "$VENV/bin/gunicorn" conciliador.wsgi:application \
  --chdir app \
  --bind "0.0.0.0:${WEBSITES_PORT:-8000}" \
  --workers "$WORKERS" \
  --threads "${GUNICORN_THREADS:-1}" \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
