#!/usr/bin/env bash
# Testa a restauração de um backup SQLite do piloto sem tocar no banco em uso.
#
# Uso: deploy/restore-test.sh /caminho/para/conciliador-YYYYMMDD-HHMMSS.sqlite3
#
# O script copia o backup para um diretório temporário, confere a integridade, valida
# que as migrações estão aplicadas e mostra as contagens. Não altera o arquivo original.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "uso: $0 <arquivo-de-backup.sqlite3>" >&2
  exit 2
fi

backup="$1"
if [[ ! -f "$backup" ]]; then
  echo "backup não encontrado: $backup" >&2
  exit 2
fi

cd "$(dirname "$0")/.."
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
restored="$tmp/restored.sqlite3"
cp "$backup" "$restored"

echo "1/4 integridade do arquivo"
integrity="$(sqlite3 "$restored" 'PRAGMA integrity_check;')"
if [[ "$integrity" != "ok" ]]; then
  echo "FALHOU: PRAGMA integrity_check devolveu: $integrity" >&2
  exit 1
fi

echo "2/4 tabelas esperadas"
tables="$(sqlite3 "$restored" "SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN ('accounts_user','ledger_company','ledger_banktransaction','ledger_expecteditem','ledger_link','ledger_auditlog');")"
if [[ "$tables" != "6" ]]; then
  echo "FALHOU: esperava 6 tabelas principais, encontrei $tables" >&2
  exit 1
fi

echo "3/4 migrações do Django"
SQLITE_PATH="$restored" uv run python app/manage.py migrate --check
SQLITE_PATH="$restored" uv run python app/manage.py showmigrations --plan >/dev/null

echo "4/4 contagens"
sqlite3 "$restored" "SELECT 'empresas', count(*) FROM ledger_company UNION ALL SELECT 'lançamentos', count(*) FROM ledger_banktransaction UNION ALL SELECT 'itens', count(*) FROM ledger_expecteditem UNION ALL SELECT 'vínculos', count(*) FROM ledger_link UNION ALL SELECT 'auditoria', count(*) FROM ledger_auditlog;"

echo "OK: backup restaurado e legível."
