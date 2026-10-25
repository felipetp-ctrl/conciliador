# AGENTS.md

Fonte única de instruções para qualquer IA (Claude, Codex, DeepSeek etc.) que trabalhe neste repositório.

## Visão do projeto

`conciliador-core` é uma biblioteca Python de código aberto (Apache-2.0) que concilia financeiramente
documentos fiscais brasileiros com extratos bancários: lê os arquivos, gera os itens esperados e sugere
vínculos entre eles, apontando o que está só no banco, só nos documentos e as divergências. Formatos
implementados: **OFX** (extrato, v1 SGML e v2 XML), **NF-e** (XML, leiaute 4.00, com evento de
cancelamento), **NFS-e nacional** (XML, leiaute 1.01, com cancelamento e substituição) e **CSV** de
contas a pagar/receber. É um workspace uv com `packages/conciliador-core` (a biblioteca) e `tools/synthetic-data`
(gerador de dados sintéticos). A especificação está em
[docs/specs/2026-10-24-conciliador-design.md](docs/specs/2026-10-24-conciliador-design.md).
**A pasta `docs/` é local e não versionada** (está no `.gitignore`); o link só funciona na máquina de quem a tem.

## Comandos

```bash
uv sync --locked                                           # instalar dependências (lockfile)
uv run pytest                                              # testes
uv run pytest --cov=conciliador_core --cov-fail-under=90   # testes com cobertura (exigido no CI)
uv run ruff check && uv run ruff format --check            # lint e formatação
uv run mypy packages/conciliador-core/src tools/synthetic-data/src   # tipos (strict)
uv run bandit -c pyproject.toml -r packages tools -q       # segurança estática
uv export --format requirements-txt --no-hashes --no-emit-workspace > /tmp/req.txt && uv run pip-audit -r /tmp/req.txt --no-deps --disable-pip   # auditoria de dependências
```

## Mapa de módulos

`packages/conciliador-core/src/conciliador_core/`:

- `__init__.py` — API pública (reexporta modelos, leitores e motor) e `__version__`.
- `errors.py` — `ParseError(code, message)`, único erro dos leitores.
- `money.py` — `parse_brl_amount` e `parse_ofx_amount`: texto → centavos inteiros.
- `documents.py` — CPF/CNPJ (inclusive alfanumérico): validação, `cnpj_root`, `find_documents`, `document_spans`, `mask_cpf`.
- `text.py` — `clean_text`/`has_unsafe_chars`: única fonte da limpeza de controles, bidi e largura zero.
- `models.py` — `BankTransaction`, `Statement`, `ExpectedItem` e enums (`Direction`, `Source`, `ItemStatus`).
- `dedup.py` — chave de deduplicação de lançamentos e `deduplicate_transactions`.
- `parsers/_limits.py` — `MAX_FILE_BYTES` (10 MB) e `MAX_XML_BYTES` (2 MB).
- `parsers/_xml.py` — `safe_parse_xml` (defusedxml, sem DTD/entidades, com limite).
- `parsers/ofx.py` — `parse_ofx`: um extrato por arquivo, tokenizador próprio (sem parser XML).
- `parsers/fiscal.py` — `parse_fiscal_xml`: NF-e, NFS-e nacional e eventos de cancelamento.
- `parsers/csv_items.py` — `parse_items_csv` e `template_csv` (modelo em `templates/contas.csv`).
- `engine/config.py` — `MatchConfig` (janela de dias e tolerância).
- `engine/matcher.py` — `SuggestionProvider`, `RuleBasedProvider` (regras DOCUMENT, NUMBER, UNIQUE, AMBIGUOUS).
- `engine/duplicates.py` — `find_probable_duplicates` entre origens diferentes.
- `engine/status.py` — `classify_item` → `ItemSituation` (quitado, pendente, vencido, cancelado).
- `engine/balance.py` — `check_balance` (saldo final) e `has_gap` (lacuna entre extratos).

`tools/synthetic-data/src/conciliador_synth/` (só para testes, nunca dado real):

- `ofx.py` — `make_ofx`: OFX sintético v1/v2, cp1252/UTF-8.
- `fiscal.py` — `make_nfe`, `make_nfe_cancellation`, `make_nfse`, `make_nfse_cancellation`.

## Convenção de commits

Assunto no formato `tipo(escopo): descrição (Plano N, Tarefa M)` — o assunto **termina** com
`(Plano N, Tarefa M)` (ou `(Plano N, revisão final)` na onda de correções da revisão). Commits feitos
pelo Claude terminam a mensagem com uma linha em branco e o trailer
`Claude-Session: <url da sessão>`.

## Restrições globais

- Python `>=3.12`. A única dependência de runtime do core é `defusedxml`. Qualquer dependência nova precisa de justificativa no PR.
- Dinheiro sempre em **centavos inteiros (`int`)**. É proibido usar `float` em qualquer valor monetário, inclusive nos testes.
- Identificadores no código em inglês. Mensagens voltadas ao usuário (`reason`, `ParseError.message`) em **português do Brasil**.
- **Nenhum dado real de cliente** no repositório. Os testes usam só o gerador sintético ou arquivos públicos registrados em `SOURCES.md`.
- Licença do core: **Apache-2.0**.
- A pasta `docs/` **nunca** é commitada, porque está no `.gitignore`.
- Todo XML é lido com `defusedxml`, sem DTD e sem entidades externas.
- Limite de tamanho por arquivo: `MAX_FILE_BYTES = 10 * 1024 * 1024`. Acima disso, `ParseError(code="too_large")`. XML (NF-e, NFS-e, eventos) tem limite menor: `MAX_XML_BYTES = 2 * 1024 * 1024`.
- Janela padrão de conciliação: de **5 dias antes** a **10 dias depois** do vencimento, com os dois limites inclusive. Tolerância padrão de **0 centavos**, configurável de 0 a 100 centavos.
- Vencimento padrão de nota sem duplicata: emissão + **30 dias**.
- Comparação "emitida ou recebida" feita pela **raiz do CNPJ** (8 primeiros caracteres).
- O CNPJ **alfanumérico** (vigente desde julho de 2026) é suportado em todo lugar onde há CNPJ.
- Toda ação do GitHub no CI é fixada por **SHA completo do commit**.

## Glossário (código ↔ interface)

| Código | Interface (pt-BR) |
|---|---|
| `ExpectedItem` | item esperado |
| `INFLOW` | a receber / crédito |
| `OUTFLOW` | a pagar / débito |
| `Suggestion` | sugestão de vínculo |
| (resultado) | "só no banco" (lançamento sem documento) |
| (resultado) | "só nos documentos" (item esperado sem lançamento) |
| (resultado) | divergência (vínculo com valor ou data fora do esperado) |

## Regras para o Plano 2 (app)

- **Filtre `existing` pela conta** antes de chamar `deduplicate_transactions`: o `fitid` é
  comparado globalmente e `BankTransaction` não guarda a conta, então um `fitid` repetido em outra
  conta descartaria um lançamento novo.
- **Nunca assuma `gross_cents − soma(withholdings) == amount_cents` na NFS-e**: PIS/COFINS retidos
  não são mapeados; o valor líquido vem de `valores/vLiq` quando presente.
- **Não passe duplicatas prováveis em `excluded_item_ids`**. Esse parâmetro é para itens que a
  pessoa removeu ou mesclou. Duplicatas não resolvidas já viram `AMBIGUOUS` quando empatam e
  precisam continuar vinculáveis por `DOCUMENT`/`NUMBER`.
- **`cancelled_ids` são prefixos de id** (`"nfe:<chave>"`, `"nfse:<chave>"`): marque como
  cancelados os itens com `item.id.startswith(c + ":")`. A NFS-e substituta também devolve a
  substituída em `cancelled_ids`.
- **Escape fórmulas** ao exportar CSV/planilha com texto não confiável (`memo`, `xNome`/
  `counterpart_name`, `descricao`): prefixe com `'` valores que começam com `=`, `+`, `-`, `@`,
  tab ou CR.

## Regras para IAs

- **Nenhuma IA faz merge.** Só uma pessoa aprova e faz merge de PRs.
- **Nunca envie dados reais ou segredos a IAs** (XMLs, extratos, CNPJs de clientes, tokens, chaves).
- **Dependência nova exige justificativa** no PR.
- Nunca faça commit de `docs/` nem de `.superpowers/`.
