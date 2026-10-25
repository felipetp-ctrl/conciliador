# AGENTS.md

Fonte única de instruções para qualquer IA (Claude, Codex, DeepSeek etc.) que trabalhe neste repositório.

## Visão do projeto

`conciliador-core` é uma biblioteca Python de código aberto (Apache-2.0) que concilia financeiramente
documentos fiscais brasileiros (NF-e/XML) com extratos bancários (OFX/CNAB): lê os arquivos, gera os
itens esperados e sugere vínculos entre eles, apontando o que está só no banco, só nos documentos e as
divergências. É um workspace uv com `packages/conciliador-core` (a biblioteca) e `tools/synthetic-data`
(gerador de dados sintéticos). A especificação está em
[docs/specs/2026-10-24-conciliador-design.md](docs/specs/2026-10-24-conciliador-design.md).
**A pasta `docs/` é local e não versionada** (está no `.gitignore`); o link só funciona na máquina de quem a tem.

## Comandos

```bash
uv sync                                                    # instalar dependências
uv run pytest                                              # testes
uv run pytest --cov=conciliador_core --cov-fail-under=90   # testes com cobertura (exigido no CI)
uv run ruff check && uv run ruff format --check            # lint e formatação
uv run mypy packages/conciliador-core/src tools/synthetic-data/src   # tipos (strict)
uv run bandit -c pyproject.toml -r packages tools -q       # segurança estática
uv export --format requirements-txt --no-hashes --no-emit-workspace > /tmp/req.txt && uv run pip-audit -r /tmp/req.txt --no-deps --disable-pip   # auditoria de dependências
```

## Restrições globais

- Python `>=3.12`. A única dependência de runtime do core é `defusedxml`. Qualquer dependência nova precisa de justificativa no PR.
- Dinheiro sempre em **centavos inteiros (`int`)**. É proibido usar `float` em qualquer valor monetário, inclusive nos testes.
- Identificadores no código em inglês. Mensagens voltadas ao usuário (`reason`, `ParseError.message`) em **português do Brasil**.
- **Nenhum dado real de cliente** no repositório. Os testes usam só o gerador sintético ou arquivos públicos registrados em `SOURCES.md`.
- Licença do core: **Apache-2.0**.
- A pasta `docs/` **nunca** é commitada, porque está no `.gitignore`.
- Todo XML é lido com `defusedxml`, sem DTD e sem entidades externas.
- Limite de tamanho por arquivo: `MAX_FILE_BYTES = 10 * 1024 * 1024`. Acima disso, `ParseError(code="too_large")`.
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

## Regras para IAs

- **Nenhuma IA faz merge.** Só uma pessoa aprova e faz merge de PRs.
- **Nunca envie dados reais ou segredos a IAs** (XMLs, extratos, CNPJs de clientes, tokens, chaves).
- **Dependência nova exige justificativa** no PR.
- Nunca faça commit de `docs/` nem de `.superpowers/`.
