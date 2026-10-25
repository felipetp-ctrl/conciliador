# conciliador-core

Biblioteca Python de código aberto para conciliação financeira brasileira: lê extratos
(OFX), documentos fiscais (NF-e e NFS-e em XML) e contas em CSV, e sugere vínculos entre
lançamentos bancários e itens esperados (a pagar / a receber).

- **Valores monetários são sempre centavos inteiros (`int`)**, nunca `float`.
- **Nenhum dado real é usado nos testes**: apenas dados sintéticos e arquivos públicos
  registrados em `tests/corpus/SOURCES.md`.
- Única dependência de runtime: `defusedxml`.

## Exemplo

```python
from pathlib import Path

from conciliador_core import MatchConfig, RuleBasedProvider, parse_fiscal_xml, parse_ofx

statement = parse_ofx(Path("extrato.ofx").read_bytes())
fiscal = parse_fiscal_xml(Path("nfe.xml").read_bytes(), company_cnpj="11222333000181")

suggestions = RuleBasedProvider().suggest(statement.transactions, fiscal.items, MatchConfig())
for s in suggestions:
    print(s)  # cada Suggestion liga um lançamento a um item esperado
```

Arquivos inválidos levantam `ParseError` (com `code` estável e mensagem em português).

## Licença

Apache-2.0. Veja `AGENTS.md` na raiz do repositório para as regras do projeto.
