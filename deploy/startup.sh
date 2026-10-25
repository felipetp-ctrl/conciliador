#!/usr/bin/env bash
# Azure App Service (Linux, Python) — inicialização do conciliador.
# Configure em App Service › Configuration › Startup Command:  bash deploy/startup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

python -m pip install --upgrade pip
python -m pip install --disable-pip-version-check -r deploy/requirements.txt

python app/manage.py migrate --noinput
python app/manage.py collectstatic --noinput

exec gunicorn conciliador.wsgi:application \
  --chdir app \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
