# Deploy do app (Azure App Service)

O app é Django + HTMX, servido por **gunicorn** e com os estáticos servidos pelo
**WhiteNoise**. Há dois modos de banco:

| Modo | Quando usar | Como |
|---|---|---|
| **SQLite no `/home`** | piloto/apresentação, uma instância | `SQLITE_PATH=/home/data/conciliador.sqlite3` |
| **PostgreSQL** | produção de verdade | `DATABASE_URL=postgres://…` |

O código é o mesmo; a escolha é só variável de ambiente. O `startup.sh` detecta
`SQLITE_PATH` e sobe **1 worker** (com 4 threads) para não disputar escrita no arquivo.

## 1. Conta Azure

Sem CNPJ a conta é **individual (CPF)**, mas dá para criar um **tenant próprio** do
projeto — separado da conta Azure for Students — e migrar para CNPJ quando a empresa
existir.

1. Crie o tenant em [entra.microsoft.com](https://entra.microsoft.com) → *Identity* →
   *Overview* → *Manage tenants* → *Create*. Use `conciliador.onmicrosoft.com` e um
   admin `admin@conciliador.onmicrosoft.com` (não use @gmail/@hotmail como único admin).
2. Assine o Azure em [azure.microsoft.com/free](https://azure.microsoft.com/free/)
   entrando com esse admin. Preencha CPF, endereço e cartão.
3. Ative MFA, crie uma conta de emergência e um **budget alert** (ex.: US$ 20/mês).
4. No terminal: `az login --tenant conciliador.onmicrosoft.com` e confirme a assinatura
   com `az account show`.

## 2. Recursos (piloto SQLite, Brazil South)

```bash
RG=rg-conciliador-prod
APP=conciliador-prod-<sufixo>       # globalmente único
PLAN=asp-conciliador-prod
LOCATION=brazilsouth

az group create -n "$RG" -l "$LOCATION"
az appservice plan create -g "$RG" -n "$PLAN" --is-linux --sku B1
az webapp create -g "$RG" -p "$PLAN" -n "$APP" --runtime "PYTHON:3.12"
```

## 3. App Settings

```bash
az webapp config appsettings set -g "$RG" -n "$APP" --settings \
  DEBUG=0 \
  SECRET_KEY="<gere com openssl rand -base64 48>" \
  SQLITE_PATH=/home/data/conciliador.sqlite3 \
  STATIC_ROOT=/home/staticfiles \
  ALLOWED_HOSTS="$APP.azurewebsites.net" \
  CSRF_TRUSTED_ORIGINS="https://$APP.azurewebsites.net" \
  WEB_CONCURRENCY=1 \
  GUNICORN_THREADS=4 \
  SCM_DO_BUILD_DURING_DEPLOYMENT=0 \
  WEBSITES_PORT=8000

az webapp config set -g "$RG" -n "$APP" --startup-file "bash deploy/startup.sh"
az webapp config set -g "$RG" -n "$APP" --always-on true
```

O health check do App Service deve apontar para `/health` (Configuration › Health check).
A rota responde `{"status":"ok"}` com 200 e `{"status":"error"}` com 503 se o banco não
responder.

## 4. Deploy

O pacote é o repositório versionado (sem `.venv`, `docs/` nem banco local):

```bash
git archive --format=zip -o /tmp/conciliador.zip HEAD
az webapp deploy -g "$RG" -n "$APP" --src-path /tmp/conciliador.zip --type zip
```

No primeiro start o `startup.sh` cria o venv em `/home/venv`, instala
`deploy/requirements.txt`, faz backup do SQLite (se existir), roda `migrate`,
`collectstatic` e sobe o gunicorn.

## 5. Backup e migração para PostgreSQL

- O SQLite fica em `/home/data` (persistente entre reinícios e deploys). A cada start o
  script copia o arquivo para `/home/backups` e mantém os **7 últimos**.
- Para baixar uma cópia: *Advanced Tools (Kudu)* → *Debug console* → `/home/backups`.
- Para migrar para PostgreSQL: crie o servidor, defina `DATABASE_URL`, remova
  `SQLITE_PATH`, rode `migrate` e importe os dados com `dumpdata`/`loaddata` (ou
  `pgloader`). O schema é o mesmo.
- SQLite no App Service **não é produção de verdade**: uma instância, sem HA e sem
  backup gerenciado. Use só no piloto.

## 6. GitHub Actions (OIDC)

Sem segredo de longa duração: o workflow troca um token do GitHub por credencial Azure.

1. Crie um *App registration* e uma **credencial federada** para o repositório
   (`repo:<org>/<repo>:ref:refs/heads/main`).
2. Dê **Contributor só no resource group** para o service principal.
3. No GitHub, configure as variáveis `AZURE_RESOURCE_GROUP` e `AZURE_WEBAPP_NAME` e os
   secrets `AZURE_CLIENT_ID`, `AZURE_TENANT_ID` e `AZURE_SUBSCRIPTION_ID`.
4. O workflow empacota com `git archive` e chama `az webapp deploy`.

## Dependências de produção

`deploy/requirements.txt` é gerado pelo uv a partir do pacote `conciliador-app`:

```bash
uv export --package conciliador-app --format requirements-txt --no-hashes > deploy/requirements.txt
```

Ele inclui `-e ./packages/conciliador-core` (o core é um membro do workspace) e não inclui
as ferramentas de desenvolvimento.
