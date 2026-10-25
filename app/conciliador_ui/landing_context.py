"""Contexto estático da landing (dados sintéticos de demonstração). Os tempos das cenas (a/b) são calculados aqui
para o template ficar sem aritmética. Espelha ui_kits/site/Scenes.jsx."""


def _qa():
    base = [
        (
            "01",
            "Quem me pagou e quem ainda me deve?",
            [
                ("Recebido", "ok", 1248000),
                ("A receber", "pending", 325000),
                ("Atrasado", "late", 98500),
            ],
            None,
        ),
        (
            "02",
            "O que eu já paguei e o que está em aberto?",
            [("Pago", "ok", 412190), ("A pagar", "pending", 21000)],
            None,
        ),
        (
            "03",
            "Entrou ou saiu dinheiro que eu não sei explicar?",
            [("Não identificado", "unid", 16990)],
            "2 lançamentos sem documento",
        ),
    ]
    out = []
    for i, (n, q, rs, nota) in enumerate(base):
        a = round(0.10 + i * 0.24, 3)
        out.append(
            {
                "n": n,
                "pergunta": q,
                "a": a,
                "b": round(a + 0.20, 3),
                "nota": nota,
                "respostas": [{"label": lbl, "tone": t, "cents": c} for lbl, t, c in rs],
            }
        )
    return out


COLUNAS = [
    {"label": "Bateu", "tone": "ok", "sub": "banco e documento"},
    {"label": "Só no banco", "tone": "unid", "sub": "sem documento"},
    {"label": "Só nos documentos", "tone": "pending", "sub": "sem lançamento"},
]
TRIAGEM_BASE = [
    (0, "21/10", "Pix recebido · Alfa Serviços", 190000, "ok"),
    (1, "02/10", "Tarifa pacote de serviços", -1990, "unid"),
    (2, "venc. 15/10", "NF-e nº 000124 · Delta", 98500, "late"),
    (0, "10/10", "Boleto · Zeta Imóveis", -350000, "ok"),
    (1, "23/10", "Pix recebido · J. Silva", 15000, "unid"),
    (2, "venc. 30/10", "NFS-e nº 000135 · Alfa", 240000, "pending"),
    (0, "07/10", "Débito · Energia Ômega", -61240, "ok"),
]


def _triagem():
    slots = [0, 0, 0]
    out = []
    for i, (col, date, memo, cents, tone) in enumerate(TRIAGEM_BASE):
        slot = slots[col]
        slots[col] += 1
        a = round(0.14 + i * 0.075, 3)
        out.append(
            {
                "date": date,
                "memo": memo,
                "cents": cents,
                "tone": tone,
                "a": a,
                "b": round(a + 0.22, 3),
                "x0": 34.25,
                "y0": 150 + i * 12,
                "x1": round(col * 34.25, 2),
                "y1": 72 + slot * 70,
                "r": round((i - 3) * 2.2, 1),
                "z": 10 - i,
            }
        )
    return out


def _fita():
    rows = [
        ("Saldo inicial", "", 3812040),
        ("Entradas", "+", 2145000),
        ("Saídas", "\u2212", 1636030),
    ]
    return [
        {
            "label": lbl,
            "op": op,
            "cents": c,
            "a": round(0.10 + i * 0.12, 2),
            "b": round(0.26 + i * 0.12, 2),
        }
        for i, (lbl, op, c) in enumerate(rows)
    ]


def landing_context():
    vocab = ["conciliado", "pendente", "atrasado", "nao_identificado", "divergencia"]
    return {
        "hero_facts": ["mesmo valor", "CNPJ no histórico", "1 dia após o vencimento"],
        "conv_facts": ["mesmo valor", "CNPJ no histórico", "1 dia após o vencimento"],
        "perguntas": _qa(),
        "colunas": [dict(c, x=round(i * 34.25, 2)) for i, c in enumerate(COLUNAS)],
        "triagem": _triagem(),
        "fita": _fita(),
        "fita_total": 3812040 + 2145000 - 1636030,
        "demo_balance": {
            "opening": 3812040,
            "inflows": 2145000,
            "outflows": 1636030,
            "closing_calc": 4321010,
            "statement_closing": 4321010,
            "diff": 0,
        },
        "vocab_status": [
            {"status": s, "a": round(0.2 + i * 0.06, 2), "b": round(0.4 + i * 0.06, 2)}
            for i, s in enumerate(vocab)
        ],
        "passos": [
            {
                "titulo": "Envie os dois lados",
                "texto": "O extrato do banco em OFX e os documentos: XML das notas e a planilha de contas.",
                "visual": "site/_passo_envio.html",
                "order_text": 1,
                "order_visual": 2,
            },
            {
                "titulo": "Confira o que casou",
                "texto": "Regras simples e visíveis: mesmo valor, CNPJ ou número da nota no histórico, dentro do prazo.",
                "visual": "site/_passo_confere.html",
                "order_text": 2,
                "order_visual": 1,
            },
            {
                "titulo": "Confirme e feche",
                "texto": "Nada é conciliado sem você. Quando o saldo bate com o do banco, o mês está fechado.",
                "visual": "site/_passo_fecha.html",
                "order_text": 1,
                "order_visual": 2,
            },
        ],
        "seguranca": [
            {
                "icon": "shield-check",
                "titulo": "Arquivos apagados após a leitura",
                "texto": "Por padrão não guardamos o OFX nem os XML. Você pode escolher guardar.",
            },
            {
                "icon": "lock",
                "titulo": "MFA obrigatório e isolamento por empresa",
                "texto": "Cada empresa só enxerga os próprios dados, garantido também no banco de dados.",
            },
            {
                "icon": "eye-off",
                "titulo": "CPF mascarado",
                "texto": "Pessoas físicas aparecem como ***.123.456-** nas telas e nunca entram nos logs.",
            },
            {
                "icon": "download",
                "titulo": "Seus dados, sempre exportáveis",
                "texto": "Exportação completa e exclusão da conta a qualquer momento, como pede a LGPD.",
            },
        ],
        "regras": [
            {"nome": "Regra 1", "fatos": "mesmo valor · CPF/CNPJ no histórico · dentro do prazo"},
            {
                "nome": "Regra 2",
                "fatos": "mesmo valor · nº do documento no histórico · dentro do prazo",
            },
            {"nome": "Regra 3", "fatos": "mesmo valor · dentro do prazo · candidato único"},
        ],
    }
