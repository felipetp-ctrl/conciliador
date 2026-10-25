# Deploy do app (Azure App Service)

O app é Django + HTMX, servido por **gunicorn** e com os estáticos servidos pelo
**WhiteNoise**. Em produção o banco é **PostgreSQL**; em desenvolvimento continua SQLite.

## Variáveis de ambiente obrigatórias

| Variável | Exemplo | Observação |
|---|---|---|
| `DEBUG` | `0` | sem isso o app sobe em modo de desenvolvimento |
| `SECRET_KEY` | valor aleatório longo | nunca reaproveite o fallback de dev |
| `DATABASE_URL` | `postgres://user:senha@host:5432/conciliador?sslmode=require` | o `sslmode` também pode vir em `DATABASE_SSLMODE` |
| `ALLOWED_HOSTS` | `conciliador.azurewebsites.net` | lista separada por vírgula |
| `CSRF_TRUSTED_ORIGINS` | `https://conciliador.azurewebsites.net` | necessário para POST atrás do proxy |

Opcionais: `SECURE_SSL_REDIRECT=1` (depois de confirmar HTTPS), `SECURE_HSTS_SECONDS`,
`LOG_LEVEL`, `WEB_CONCURRENCY` e `PORT`.

## Passos

1. Crie o App Service (Linux, Python 3.12) e um PostgreSQL flexível.
2. Em **Configuration**, defina as variáveis acima e o **Startup Command**:
   `bash deploy/startup.sh`.
3. Aponte o health check do App Service para `/health`. A rota responde
   `{"status":"ok"}` com 200 e `{"status":"error"}` com 503 se o banco não responder.
4. Faça o deploy do repositório. O script instala as dependências, roda as migrações,
   coleta os estáticos e inicia o gunicorn em `0.0.0.0:8000`.

## Dependências de produção

`deploy/requirements.txt` é gerado pelo uv a partir do pacote `conciliador-app`:

```bash
uv export --package conciliador-app --format requirements-txt --no-hashes > deploy/requirements.txt
```

Ele inclui `-e ./packages/conciliador-core` (o core é um membro do workspace) e não inclui
as ferramentas de desenvolvimento.
