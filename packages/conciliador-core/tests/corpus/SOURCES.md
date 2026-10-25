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

# Corpus fiscal (NF-e)

Nenhum XML público de NF-e foi incluído em `fiscal/`: os exemplos encontrados ou não têm licença
livre clara (amostras do Portal da NF-e) ou contêm CNPJ, razão social e endereço reais de empresas.
A cobertura vem do gerador sintético `conciliador_synth.fiscal` (`make_nfe`, `make_nfe_cancellation`).

## Apenas referência (sem cópia)

| Fonte | URL | Licença | Motivo |
|---|---|---|---|
| `procNFe.xml` do `nfelib` (akretion) | https://github.com/akretion/nfelib/blob/master/nfelib/nfe/samples/v4_0/procNFe.xml | MIT | Licença compatível, mas traz CNPJ e razão social reais de empresas; rejeitado |
| Exemplos do `sped-nfe`, `sped-da`, `nfephp` | https://github.com/nfephp-org | LGPL/MIT (variável por repositório) | Fixtures com aparência de dados reais de empresas; não copiados |
| Amostras do Portal da NF-e | https://www.nfe.fazenda.gov.br/portal/ | Sem licença explícita | Não redistribuível com segurança; não copiado |

## XSD oficial (somente conferência manual, não versionado)

Leiaute 4.00 da NF-e (Portal da NF-e, "Esquemas XML"), consultado em 2026-10-24 por meio dos
espelhos `akretion/nfelib` (`nfelib/nfe/schemas/v4_0/leiauteNFe_v4.00.xsd`, MIT) e
`nfephp-org/sped-nfe` (`schemes/PL_009_V4/leiauteEvento_v1.00.xsd`). O portal oficial respondeu com
redirecionamentos em loop a download automatizado (curl), então o XSD foi conferido pelo espelho.
Caminhos confirmados: `infNFe/@Id` (`NFe` + 44 caracteres; padrão `[0-9]{6}[0-9A-Z]{12}[0-9]{26}`, ou
seja, aceita CNPJ alfanumérico), `ide/nNF`, `ide/dhEmi`, `emit/CNPJ|CPF`, `dest/CNPJ|CPF|idEstrangeiro`,
`total/ICMSTot/vNF`, `total/retTrib/{vRetPIS,vRetCOFINS,vRetCSLL,vIRRF,vRetPrev}`,
`cobr/dup/{nDup,dVenc,vDup}`; evento: `procEventoNFe/evento/infEvento/{chNFe,tpEvento}` e
`retEvento/infEvento/cStat`.

# Corpus fiscal (NFS-e padrão nacional)

Nenhum XML de NFS-e foi incluído: a cobertura vem do gerador sintético
`conciliador_synth.fiscal` (`make_nfse`, `make_nfse_cancellation`).

## XSD oficial (somente conferência manual, não versionado)

Leiaute 1.01 da NFS-e nacional (portal gov.br/nfse, "Documentação Atual"), consultado em
2026-10-24 pelo espelho `akretion/nfelib` (`nfelib/nfse/schemas/v1_0/`, MIT): `NFSe_v1.01.xsd`,
`tiposComplexos_v1.01.xsd`, `tiposSimples_v1.01.xsd`, `evento_v1.01.xsd`, `pedRegEvento_v1.01.xsd`,
`tiposEventos_v1.01.xsd`; exemplo `nfelib/nfse/samples/v1_0/nfse-ibscbs.xml` (apenas lido; usa
CNPJ zerado, mas não foi copiado). Caminhos confirmados (namespace `http://www.sped.fazenda.gov.br/nfse`):
`NFSe/infNFSe/@Id` (`NFS` + 50 dígitos, `TSChaveNFSe` `[0-9]{50}`), `infNFSe/nNFSe`,
`infNFSe/valores/{vISSQN,vTotalRet,vLiq}` (`vLiq` obrigatório), **`infNFSe/DPS/infDPS`** (o DPS fica
dentro do `infNFSe`), `infDPS/{dhEmi,prest/CNPJ|CPF,toma/CNPJ|CPF}`, `infDPS/valores/vServPrest/vServ`,
`infDPS/valores/trib/tribMun/tpRetISSQN` (1 não retido, 2 tomador, 3 intermediário),
`infDPS/valores/trib/tribFed/{vRetCP,vRetIRRF,vRetCSLL}`; evento: raiz `evento/infEvento`
(`verAplic, ambGer, nSeqEvento, dhProc, nDFSe`, `Id` `EVT`+50+6+3) com
`pedRegEvento/infPedReg/{chNFSe, e101101}`; raiz `pedRegEvento` é só o pedido. O XSD 1.01 usa
`TSCNPJ` `[0-9]{14}` (sem letras); o parser aceita CNPJ alfanumérico por exigência do projeto.

Licença do `nfelib` verificada em 2026-10-24: **MIT** (`pyproject.toml` do repositório:
`license = {text = "MIT"}`, `license-files = ["MIT-LICENSE"]`, classificador
`License :: OSI Approved :: MIT License`; metadados do PyPI idem). Nada do `nfelib` foi copiado.
