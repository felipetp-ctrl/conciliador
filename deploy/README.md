# Deploy do app (Azure App Service)

O app é Django + HTMX, servido por **gunicorn** e com os estáticos servidos pelo
**WhiteNoise**. Há dois modos de banco:

| Modo | Quando usar | Como |
|---|---|---|
| **SQLite no `/home`** | piloto/apresentação, uma instância | `SQLITE_PATH=/home/data/conciliador.sqlite3` |
| **PostgreSQL** | produção de verdade | `DATABASE_URL=postgres://…` |

O código é o mesmo; a escolha é só variável de ambiente. O `startup.sh` detecta
`SQLITE_PATH` e sobe **1 worker** (com 4 threads) para não disputar escrita no arquivo.

## 1. Conta Azure (CPF, sem CNPJ)

A conta **Azure for Students** (`@pucpr.edu.br`) não serve: ela pertence ao tenant da
faculdade, não pode ser convertida e você não é admin dele. Crie uma conta nova com um
**e-mail pessoal** (Outlook ou Gmail).

1. Entre em [azure.microsoft.com/free](https://azure.microsoft.com/free/) e comece o
   cadastro com sua conta Microsoft pessoal. Se usar Gmail, o próprio fluxo cria a
   conta Microsoft vinculada.
2. Preencha **CPF**, endereço, CEP, telefone e cartão internacional. O Azure cria
   automaticamente um **tenant dedicado** (algo como `seunome.onmicrosoft.com`) e você
   fica Global Admin dele — não é o tenant da PUC.
   - Se o portal não oferecer os US$ 200 (o benefício pode já ter sido usado na conta
     student), escolha **pay-as-you-go**. O piloto custa ~US$ 15/mês.
   - O domínio `onmicrosoft.com` é só para login administrativo; o domínio da empresa
     (`conciliador.com.br`) pode ser adicionado depois.
3. No portal: ative MFA, crie uma conta de emergência (*break-glass*) e um
   **budget alert** (Cost Management → Budgets, ex.: US$ 20/mês).
4. No terminal:

   ```bash
   az logout
   az login          # escolha a conta pessoal nova, não a @pucpr.edu.br
   az account show --query "{name:name, id:id, tenant:tenantId, user:user.name}" -o json
   ```

   Confirme que a assinatura **não** é a “Azure for Students”.

> Criar um tenant *extra* em `entra.microsoft.com` exige licença paga ou o papel
> *Tenant Creator*; por isso o caminho acima (cadastro do Azure) é o mais confiável
> para começar. Se a empresa já tiver Microsoft 365, aí sim vale usar o tenant dela.

## 2. Criar os recursos

O script é idempotente: pode rodar de novo para ajustar configuração sem recriar nada.

```bash
RG=rg-conciliador-prod
APP=conciliador-prod   # globalmente único; se estiver ocupado, use um sufixo curto
PLAN=asp-conciliador-b1

RG="$RG" APP="$APP" PLAN="$PLAN" bash deploy/azure-setup.sh
```

Antes de qualquer dado real, rode de novo com o contato LGPD (o endereço não fica no
repositório): `LEGAL_CONTACT_EMAIL="seu-email@dominio.com"` no mesmo comando.

Ele cria o resource group em **Brazil South**, o plano **B1 Linux**, o Web App
**Python 3.12**, gera a `SECRET_KEY`, grava os App Settings, liga HTTPS/TLS 1.2,
desliga FTPS, define o startup `bash deploy/startup.sh`, o always-on e o health check
em `/health`.

O script se recusa a rodar na assinatura student; para insistir, use `ALLOW_STUDENT=1`.

## 3. App Settings (referência)

O script já define tudo. Para conferir ou ajustar à mão:

| Variável | Valor |
|---|---|
| `DEBUG` | `0` |
| `SECRET_KEY` | `openssl rand -base64 48` (não reaproveite a de dev) |
| `SQLITE_PATH` | `/home/data/conciliador.sqlite3` |
| `STATIC_ROOT` | `/home/staticfiles` |
| `ALLOWED_HOSTS` | `<APP>.azurewebsites.net,169.254.129.1` |
| `CSRF_TRUSTED_ORIGINS` | `https://<APP>.azurewebsites.net` |
| `WEB_CONCURRENCY` | `1` |
| `GUNICORN_THREADS` | `4` |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | `0` |
| `WEBSITES_PORT` | `8000` |
| `LEGAL_CONTACT_EMAIL` | e-mail do responsável pelo tratamento (aparece em Privacidade/Termos) |
| `SESSION_COOKIE_AGE` | opcional; padrão `28800` (8 horas de inatividade) |
| `MAX_UPLOAD_BYTES` | opcional; padrão `10485760` (10 MB) |

O `169.254.129.1` é a origem dos health checks internos do App Service; sem ele o
Django responde 400 e o app é marcado como não saudável. O `/health` responde
`{"status":"ok"}` com 200 e `{"status":"error"}` com 503 se o banco não responder.

`SECURE_SSL_REDIRECT` fica desligado de propósito: o redirect é feito pelo
`--https-only` do App Service, e o health check interno não deve levar 301.

## 4. Primeiro deploy (local)

Antes de existir repositório no GitHub, suba o pacote versionado direto da máquina:

```bash
git archive --format=zip -o /tmp/conciliador.zip HEAD
az webapp deploy -g "$RG" -n "$APP" --src-path /tmp/conciliador.zip --type zip --clean true
```

No primeiro start o `startup.sh` cria o venv em `/home/venv`, instala
`deploy/requirements.txt`, faz backup do SQLite (se existir), roda `migrate`,
`collectstatic` e sobe o gunicorn. Acompanhe em *Log stream* ou:

```bash
az webapp log tail -g "$RG" -n "$APP"
curl -fsS "https://$APP.azurewebsites.net/health"
```

Crie o superusuário pelo SSH do App Service:

```bash
az webapp ssh -g "$RG" -n "$APP"
cd /home/site/wwwroot && /home/venv/bin/python app/manage.py createsuperuser
```

No primeiro acesso, entre com esse usuário, **ative a verificação em duas etapas** e
cadastre a primeira empresa (nome + CNPJ). O painel só abre depois disso; não há dados
de demonstração em produção.

## 5. Deploy contínuo (GitHub Actions + OIDC)

Sem segredo de longa duração: o workflow troca um token do GitHub por credencial
Azure. O `.github/workflows/deploy.yml` publica **depois que o CI passa no `main`**
(e também por `workflow_dispatch`).

1. O repositório é **`felipetp-ctrl/conciliador`** (privado) e o branch de deploy é
   **`main`**. As variáveis `AZURE_RESOURCE_GROUP=rg-conciliador-prod` e
   `AZURE_WEBAPP_NAME=conciliador-prod` já estão configuradas nele.
2. Rode o script (precisa de permissão de admin no tenant):

   ```bash
   REPO=felipetp-ctrl/conciliador RG=rg-conciliador-prod APP=conciliador-prod bash deploy/azure-oidc.sh
   ```

   Ele cria o App registration, a credencial federada
   `repo:felipetp-ctrl/conciliador:ref:refs/heads/main` e dá **Contributor só no resource group**.
3. Rode os comandos `gh secret set` que o script imprime (ou configure em
   *Settings → Secrets and variables → Actions*). Os deploys ficam desligados até você
   ligar a chave:

   ```bash
   gh variable set AZURE_DEPLOY_ENABLED --repo felipetp-ctrl/conciliador --body true
   ```
4. Faça um push no `main`; o workflow empacota com `git archive` e chama
   `az webapp deploy`. No fim ele espera o `/health` responder 200 por até 5 minutos.

## 6. Backup, restauração e LGPD

- O SQLite fica em `/home/data` (persistente entre reinícios e deploys). A cada start o
  script copia o arquivo para `/home/backups` e mantém os **7 últimos**.
- Para baixar uma cópia: *Advanced Tools (Kudu)* → *Debug console* → `/home/backups`.
- **Teste de restauração** (não toca no banco em uso; confere integridade, tabelas e
  migrações):

  ```bash
  deploy/restore-test.sh /caminho/para/conciliador-20261025-030000.sqlite3
  ```

  Rode esse teste depois de cada mudança de schema e antes de confiar no backup. O CI
  roda o mesmo script contra um banco recém-migrado.
- **LGPD:** o titular exporta todos os dados em **Empresa → Exportar todos os dados
  (JSON)** e exclui a conta em **Empresa → Excluir minha conta**. A exclusão apaga os
  dados financeiros; os registros de acesso ficam sem vínculo com a empresa por 6 meses.
- **MFA é obrigatório:** no primeiro acesso (inclusive do superusuário), o app pede a
  ativação do TOTP antes de liberar o painel. Não há botão de desativar.
- Para migrar para PostgreSQL: crie o servidor, defina `DATABASE_URL`, remova
  `SQLITE_PATH`, rode `migrate` e importe os dados com `dumpdata`/`loaddata` (ou
  `pgloader`). O schema é o mesmo.
- SQLite no App Service **não é produção de verdade**: uma instância, sem HA e sem
  backup gerenciado. Use só no piloto.

## Dependências de produção

`deploy/requirements.txt` é gerado pelo uv a partir do pacote `conciliador-app`:

```bash
uv export --package conciliador-app --format requirements-txt --no-hashes > deploy/requirements.txt
```

Ele inclui `-e ./packages/conciliador-core` (o core é um membro do workspace) e não inclui
as ferramentas de desenvolvimento.
