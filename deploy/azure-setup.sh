#!/usr/bin/env bash
# Cria o piloto do conciliador no Azure: App Service B1 Linux (Brazil South) com
# SQLite em /home. Idempotente: pode rodar de novo para ajustar configuração.
#
# Uso:
#   RG=rg-conciliador-prod APP=conciliador-prod-abc123 PLAN=asp-conciliador-prod \
#     bash deploy/azure-setup.sh
#
# Variáveis: RG, APP (obrigatórias), PLAN, LOCATION, SKU, RUNTIME.
# Para rodar na assinatura Azure for Students de propósito: ALLOW_STUDENT=1.
set -euo pipefail

: "${RG:?defina RG (ex.: rg-conciliador-prod)}"
: "${APP:?defina APP (nome globalmente único, ex.: conciliador-prod-abc123)}"
PLAN="${PLAN:-asp-conciliador-prod}"
LOCATION="${LOCATION:-brazilsouth}"
SKU="${SKU:-B1}"
RUNTIME="${RUNTIME:-PYTHON:3.12}"

SUB_NAME="$(az account show --query name -o tsv)"
SUB_ID="$(az account show --query id -o tsv)"
echo "assinatura: $SUB_NAME ($SUB_ID)"

case "$SUB_NAME" in
  *Students*)
    if [ "${ALLOW_STUDENT:-0}" != "1" ]; then
      echo "ERRO: a assinatura atual é '$SUB_NAME'." >&2
      echo "Entre no tenant da empresa (az login --tenant ...) ou use ALLOW_STUDENT=1." >&2
      exit 1
    fi
    ;;
esac

echo "== resource group $RG ($LOCATION)"
az group create -n "$RG" -l "$LOCATION" -o none

echo "== plano $PLAN ($SKU Linux)"
if az appservice plan show -g "$RG" -n "$PLAN" -o none 2>/dev/null; then
  echo "plano já existe"
else
  az appservice plan create -g "$RG" -n "$PLAN" --is-linux --sku "$SKU" -o none
fi

echo "== web app $APP ($RUNTIME)"
if az webapp show -g "$RG" -n "$APP" -o none 2>/dev/null; then
  echo "web app já existe"
else
  az webapp create -g "$RG" -p "$PLAN" -n "$APP" --runtime "$RUNTIME" -o none
fi

# A SECRET_KEY só é gerada na primeira execução; reexecutar não derruba as sessões.
EXISTING_SECRET="$(az webapp config appsettings list -g "$RG" -n "$APP" \
  --query "[?name=='SECRET_KEY'].value | [0]" -o tsv)"
SECRET_KEY="${EXISTING_SECRET:-$(openssl rand -base64 48 | tr -d '\n')}"

echo "== app settings"
# 169.254.129.1 é a origem dos health checks internos do App Service; sem ele o
# Django responde 400 e o app é marcado como não saudável.
az webapp config appsettings set -g "$RG" -n "$APP" --settings \
  DEBUG=0 \
  SECRET_KEY="$SECRET_KEY" \
  SQLITE_PATH=/home/data/conciliador.sqlite3 \
  STATIC_ROOT=/home/staticfiles \
  ALLOWED_HOSTS="$APP.azurewebsites.net,169.254.129.1" \
  CSRF_TRUSTED_ORIGINS="https://$APP.azurewebsites.net" \
  WEB_CONCURRENCY=1 \
  GUNICORN_THREADS=4 \
  SCM_DO_BUILD_DURING_DEPLOYMENT=0 \
  WEBSITES_PORT=8000 \
  -o none

echo "== startup, HTTPS, TLS e health check"
az webapp config set -g "$RG" -n "$APP" \
  --startup-file "bash deploy/startup.sh" \
  --always-on true \
  --min-tls-version 1.2 \
  --ftps-state Disabled \
  -o none
az webapp update -g "$RG" -n "$APP" --https-only true -o none
az resource update --ids "$(az webapp show -g "$RG" -n "$APP" --query id -o tsv)" \
  --set properties.healthCheckPath="/health" -o none

cat <<EOF

Pronto. Falta o primeiro deploy (zipdeploy local ou GitHub Actions):
  URL:     https://$APP.azurewebsites.net
  saúde:   https://$APP.azurewebsites.net/health

Superusuário (depois do deploy, no SSH do App Service):
  cd /home/site/wwwroot && /home/venv/bin/python app/manage.py createsuperuser
EOF
