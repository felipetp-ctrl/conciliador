# Corpus público de OFX

Arquivos públicos usados como fixtures de teste. Só entram no repositório arquivos com licença
MIT, BSD, Apache, CC0 ou domínio público. Nenhum arquivo contém dado real de cliente: todos são
fixtures de teste de bibliotecas de código aberto, com nomes, contas e valores fictícios.

## Arquivos incluídos (cópia em `ofx/`)

Origem: projeto [ofxparse](https://github.com/jseutter/ofxparse) (Jerry Seutter), licença **MIT**.
O aviso de copyright e a licença estão em [`ofx/LICENSE-ofxparse.txt`](ofx/LICENSE-ofxparse.txt)
(Copyright (c) 2009 Jerry Seutter), conforme exigido pela licença MIT. Acessados em 2026-10-24.
URL base: `https://raw.githubusercontent.com/jseutter/ofxparse/master/tests/fixtures/`

| Arquivo | URL | Licença | Acesso | O que exercita |
|---|---|---|---|---|
| `anzcc.ofx` | `<base>/anzcc.ofx` | MIT | 2026-10-24 | OFX v2 com folhas sem fechamento (misto SGML/XML), extrato de cartão (`CCSTMTRS`) |
| `bank_medium.ofx` | `<base>/bank_medium.ofx` | MIT | 2026-10-24 | OFX v1 SGML em uma linha só, datas com fuso `[-5:EST]`, `NAME` e `MEMO` |
| `bank_small.ofx` | `<base>/bank_small.ofx` | MIT | 2026-10-24 | OFX v1 com corpo vazio (`<OFX></OFX>`) |
| `checking.ofx` | `<base>/checking.ofx` | MIT | 2026-10-24 | OFX v1 SGML indentado com tabulações, conta corrente, `INTU.BID` |
| `error_message.ofx` | `<base>/error_message.ofx` | MIT | 2026-10-24 | OFX v2 com `STATUS` de erro (código 2000) e sem transações |
| `multiple_accounts.ofx` | `<base>/multiple_accounts.ofx` | MIT | 2026-10-24 | OFX v2 com várias contas, saldo sem lançamentos |
| `ofx-v102-empty-tags.ofx` | `<base>/ofx-v102-empty-tags.ofx` | MIT | 2026-10-24 | Cabeçalho v1 com corpo XML, tags vazias, linhas em branco iniciais |
| `suncorp.ofx` | `<base>/suncorp.ofx` | MIT | 2026-10-24 | OFX v2 XML fechado, CRLF, `CDATA`, encoding `us-ascii` |

## Apenas referência (sem cópia)

| Fonte | URL | Licença | Motivo |
|---|---|---|---|
| Fixtures do `ofxtools` | https://github.com/csingley/ofxtools | GPL-3.0 | Licença incompatível; não copiado |
| Especificação OFX 1.0.2 / 2.2 | https://www.ofx.net/ | Termos próprios da OFX.net | Sem licença livre explícita; não copiado |

## Observações

- Não há exemplos de bancos brasileiros (cp1252 com acentos, vírgula decimal): esses casos são
  cobertos pelo gerador sintético `conciliador_synth.ofx.make_ofx`.
- Fixtures do `ofxparse` descartadas por não serem extratos bancários (investimento): `fidelity*.ofx`,
  `investment_*.ofx`, `td_ameritrade.ofx`, `tiaacref.ofx`, `vanguard*.ofx`.
