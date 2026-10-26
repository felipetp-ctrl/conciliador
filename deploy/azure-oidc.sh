#!/usr/bin/env bash
# Configura o deploy por GitHub Actions com OIDC (sem segredo de longa duração).
#
# Uso:
#   REPO=felipetp-ctrl/conciliador RG=rg-conciliador-prod APP=conciliador-prod \
#     bash deploy/azure-oidc.sh
#
# Cria (ou reaproveita) o App registration, a credencial federada para o branch
# main e o Contributor restrito ao resource group. No fim imprime os comandos
# `gh secret/variable set` para colar no repositório.
set -euo pipefail

: "${REPO:?defina REPO no formato dono/repositório}"
: "${RG:?defina RG (resource group do app)}"
: "${APP:?defina APP (nome do web app)}"
APP_NAME="${APP_NAME:-conciliador-github}"
BRANCH="${BRANCH:-main}"

SUB_ID="$(az account show --query id -o tsv)"
TENANT_ID="$(az account show --query tenantId -o tsv)"
RG_ID="$(az group show -n "$RG" --query id -o tsv)"

echo "== app registration $APP_NAME"
CLIENT_ID="$(az ad app list --display-name "$APP_NAME" --query "[0].appId" -o tsv)"
if [ -z "$CLIENT_ID" ]; then
  CLIENT_ID="$(az ad app create --display-name "$APP_NAME" --query appId -o tsv)"
  echo "criado: $CLIENT_ID"
else
  echo "reaproveitado: $CLIENT_ID"
fi

echo "== service principal"
SP_ID="$(az ad sp show --id "$CLIENT_ID" --query id -o tsv 2>/dev/null || true)"
if [ -z "$SP_ID" ]; then
  SP_ID="$(az ad sp create --id "$CLIENT_ID" --query id -o tsv)"
fi

echo "== credencial federada (repo:$REPO, branch $BRANCH)"
SUBJECT="repo:$REPO:ref:refs/heads/$BRANCH"
CRED_NAME="github-$BRANCH-$(printf '%s' "$REPO" | tr '/' '-')"
EXISTING="$(az ad app federated-credential list --id "$CLIENT_ID" \
  --query "[?subject=='$SUBJECT'].name | [0]" -o tsv)"
if [ -z "$EXISTING" ]; then
  az ad app federated-credential create --id "$CLIENT_ID" --parameters "$(cat <<JSON
{
  "name": "$CRED_NAME",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "$SUBJECT",
  "audiences": ["api://AzureADTokenExchange"]
}
JSON
)" -o none
  echo "criada"
else
  echo "já existe: $EXISTING"
fi

echo "== Contributor só no resource group"
HAS_ROLE="$(az role assignment list --assignee "$SP_ID" --scope "$RG_ID" \
  --query "[?roleDefinitionName=='Contributor'] | [0].id" -o tsv)"
if [ -z "$HAS_ROLE" ]; then
  az role assignment create \
    --assignee-object-id "$SP_ID" \
    --assignee-principal-type ServicePrincipal \
    --role Contributor \
    --scope "$RG_ID" -o none
  echo "concedido"
else
  echo "já concedido"
fi

cat <<EOF

Configure no GitHub (repo $REPO):

  gh secret set AZURE_CLIENT_ID --repo "$REPO" --body "$CLIENT_ID"
  gh secret set AZURE_TENANT_ID --repo "$REPO" --body "$TENANT_ID"
  gh secret set AZURE_SUBSCRIPTION_ID --repo "$REPO" --body "$SUB_ID"
  gh variable set AZURE_RESOURCE_GROUP --repo "$REPO" --body "$RG"
  gh variable set AZURE_WEBAPP_NAME --repo "$REPO" --body "$APP"

O workflow .github/workflows/deploy.yml roda depois do CI passar no main.
EOF
