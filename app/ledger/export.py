"""Exportações do demonstrativo: CSV seguro e PDF em A4.

Regras que valem para os dois formatos:

- dinheiro sempre em centavos inteiros, formatado como ``1234,56``;
- CPF sai mascarado (``***.222.333-**``); CNPJ sai formatado;
- texto vindo do arquivo (histórico, contraparte) é tratado como não confiável: no CSV,
  fórmula é neutralizada com ``'``; no PDF, caracteres fora do latin-1 viram ``?``.
"""

from __future__ import annotations

import csv
import io

from conciliador_core.documents import only_alnum
from conciliador_ui import vocab
from fpdf import FPDF

_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")
_COLUMNS = (
    "Situação",
    "Data",
    "Histórico do extrato",
    "Documento",
    "Vencimento",
    "Extrato (R$)",
    "Documento (R$)",
    "Diferença (R$)",
    "Contraparte",
    "CPF/CNPJ",
    "Explicação",
)
_SHORT_STATUS = {
    "conciliado": "Conciliado",
    "a_confirmar": "A confirmar",
    "pendente": "Em aberto",
    "atrasado": "Vencido",
    "nao_identificado": "Só no banco",
    "divergencia": "Divergência",
    "classificado": "Classificado",
    "transferencia": "Transferência",
    "cancelado": "Cancelado",
}


def safe_text(value: str | None) -> str:
    """Neutraliza fórmula de planilha em texto não confiável."""
    text = (value or "").strip()
    return "'" + text if text.startswith(_DANGEROUS) else text


def money(cents: int | None) -> str:
    if cents is None:
        return ""
    sign = "-" if cents < 0 else ""
    value = abs(int(cents))
    return f"{sign}{value // 100},{value % 100:02d}"


def format_document(raw: str | None) -> str:
    value = only_alnum(raw or "")
    if len(value) == 11 and value.isdigit():
        return f"***.{value[3:6]}.{value[6:9]}-**"
    if len(value) == 14:
        return f"{value[:2]}.{value[2:5]}.{value[5:8]}/{value[8:12]}-{value[12:]}"
    return value


def _bank_cents(item: dict) -> int | None:
    if item.get("bank"):
        return item["bank"]["cents"]
    if item.get("bank_many"):
        return sum(b["cents"] for b in item["bank_many"])
    return None


def _doc_cents(item: dict) -> int | None:
    if item.get("doc"):
        return item["doc"]["cents"]
    if item.get("doc_many"):
        return sum(d["cents"] for d in item["doc_many"])
    return None


def _bank_date(item: dict) -> str:
    banks = item.get("bank_many") or ([item["bank"]] if item.get("bank") else [])
    return " / ".join(f"{b['date']:%d/%m/%Y}" for b in banks)


def _bank_memo(item: dict) -> str:
    banks = item.get("bank_many") or ([item["bank"]] if item.get("bank") else [])
    return " / ".join(b["memo"] for b in banks)


def _docs(item: dict) -> list[dict]:
    return item.get("doc_many") or ([item["doc"]] if item.get("doc") else [])


def _doc_label(item: dict) -> str:
    return " / ".join(f"{d['kind']} {d['number']}".strip() for d in _docs(item))


def _due(item: dict) -> str:
    docs = _docs(item)
    if not docs:
        return ""
    return " / ".join(f"{d['due']:%d/%m/%Y}" for d in docs)


def _counterpart(item: dict) -> str:
    return " / ".join(d["counterpart"] for d in _docs(item) if d.get("counterpart"))


def _document_id(item: dict) -> str:
    return " / ".join(format_document(d["doc_id"]) for d in _docs(item) if d.get("doc_id"))


def _explanation(item: dict) -> str:
    parts = list(item.get("facts") or [])
    if item.get("rule") and item["status"] in ("a_confirmar", "classificado"):
        parts.insert(0, item["rule"])
    if item["status"] == "transferencia":
        parts.append("transferência entre contas")
    return " · ".join(dict.fromkeys(p for p in parts if p))


def _difference(item: dict) -> int | None:
    if item["status"] in ("divergencia",) or item.get("diff_cents"):
        return item.get("diff_cents")
    return None


def csv_bytes(ctx: dict) -> bytes:
    """CSV com ``;`` (padrão pt-BR), BOM para o Excel e fórmulas neutralizadas."""
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\n")
    org = ctx["org"]
    period = ctx["periodo"]
    writer.writerow(["Empresa", safe_text(org["name"])])
    writer.writerow(["CNPJ", format_document(org["cnpj"])])
    if ctx.get("conta"):
        writer.writerow(["Conta", safe_text(ctx["conta"]["label"])])
    writer.writerow(
        [
            "Período",
            f"{period['start']:%d/%m/%Y} a {period['end']:%d/%m/%Y}"
            if period.get("start")
            else "Período atual",
        ]
    )
    writer.writerow([])
    writer.writerow(_COLUMNS)
    for item in ctx["items"]:
        writer.writerow(
            [
                vocab.status_label(item["status"], "contador", item["direction"]),
                _bank_date(item),
                safe_text(_bank_memo(item)),
                safe_text(_doc_label(item)),
                _due(item),
                money(_bank_cents(item)),
                money(_doc_cents(item)),
                money(_difference(item)),
                safe_text(_counterpart(item)),
                _document_id(item),
                safe_text(_explanation(item)),
            ]
        )
    return ("\ufeff" + out.getvalue()).encode("utf-8")


def _latin(text: str) -> str:
    text = (
        text.replace("\u2212", "-")
        .replace("\u2014", "-")
        .replace("\u2013", "-")
        .replace("\u2026", "...")
        .replace("\u00a0", " ")
    )
    return text.encode("cp1252", "replace").decode("cp1252")


class _Document(FPDF):
    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self._title = title
        self._subtitle = subtitle
        self.set_margins(14, 14, 14)
        self.set_top_margin(32)
        self.set_auto_page_break(auto=True, margin=20)

    def header(self) -> None:
        self.set_fill_color(15, 18, 21)
        self.rect(0, 0, 210, 24, "F")
        self.set_text_color(244, 245, 245)
        self.set_font("Helvetica", "B", 13)
        self.set_xy(14, 6)
        self.cell(0, 7, _latin(self._title))
        self.set_font("Helvetica", "", 8.5)
        self.set_xy(14, 14)
        self.cell(0, 5, _latin(self._subtitle))
        self.set_text_color(90, 96, 105)
        self.set_y(32)

    def footer(self) -> None:
        self.set_y(-14)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(120, 126, 134)
        self.cell(0, 6, f"conciliador · página {self.page_no()}", align="C")


def _clip(pdf: FPDF, text: str, width: float) -> str:
    text = _latin(text)
    if pdf.get_string_width(text) <= width:
        return text
    while text and pdf.get_string_width(text + "...") > width:
        text = text[:-1]
    return text + "..."


def _summary(pdf: FPDF, ctx: dict) -> None:
    balance = ctx["balance"]
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(90, 96, 105)
    pdf.set_x(14)
    pdf.cell(89, 5, "EXTRATO")
    pdf.set_x(110)
    pdf.cell(86, 5, "CONTROLE INTERNO")
    pdf.ln(6)

    rows = [
        (
            "Saldo inicial",
            money(balance["opening"]),
            "Recebimentos baixados",
            money(balance["settled_in"]),
        ),
        (
            "Créditos",
            money(balance["statement_inflows"]),
            "Pagamentos baixados",
            money(balance["settled_out"]),
        ),
        (
            "Débitos",
            money(balance["statement_outflows"]),
            "Receitas classificadas",
            money(balance["classified_in"]),
        ),
        (
            "Saldo final do extrato",
            money(balance["statement_closing"]),
            "Despesas classificadas",
            money(balance["classified_out"]),
        ),
        ("", "", "Saldo do controle", money(balance["ledger_closing"])),
    ]
    pdf.set_font("Helvetica", "", 8.5)
    for left_label, left_value, right_label, right_value in rows:
        y = pdf.get_y()
        pdf.set_text_color(90, 96, 105)
        pdf.set_x(14)
        pdf.cell(58, 6, _latin(left_label))
        pdf.set_text_color(15, 18, 21)
        pdf.set_x(72)
        pdf.cell(31, 6, _latin(left_value), align="R")
        pdf.set_text_color(90, 96, 105)
        pdf.set_x(110)
        pdf.cell(55, 6, _latin(right_label))
        pdf.set_text_color(15, 18, 21)
        pdf.set_x(165)
        pdf.cell(31, 6, _latin(right_value), align="R")
        pdf.set_y(y + 6)

    pdf.ln(3)
    y = pdf.get_y()
    pdf.set_fill_color(244, 245, 245)
    pdf.rect(14, y, 182, 20, "F")
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(90, 96, 105)
    pdf.set_xy(18, y + 4)
    pdf.cell(40, 5, "DIFERENÇA")
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(15, 18, 21)
    pdf.set_xy(58, y + 2)
    pdf.cell(134, 8, _latin(f"R$ {money(balance['difference'])}"), align="R")
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(90, 96, 105)
    explanation = (
        f"{balance['n_unexplained']} "
        f"{'lançamento' if balance['n_unexplained'] == 1 else 'lançamentos'} sem documento e "
        f"{balance['n_value_gap']} "
        f"{'baixa' if balance['n_value_gap'] == 1 else 'baixas'} com diferença de valor."
    )
    pdf.set_xy(18, y + 12)
    pdf.cell(174, 5, _latin(explanation))
    pdf.set_y(y + 24)


def _table(pdf: FPDF, ctx: dict) -> None:
    widths = (26, 17, 38, 32, 11, 17, 22, 19)
    headers = (
        "Situação",
        "Data",
        "Histórico do extrato",
        "Documento",
        "Venc.",
        "Extrato",
        "Documento",
        "Diferença",
    )
    aligns = ("L", "L", "L", "L", "L", "R", "R", "R")

    pdf.set_font("Helvetica", "B", 7.5)
    pdf.set_fill_color(226, 228, 230)
    pdf.set_text_color(48, 53, 60)
    for width, header, align in zip(widths, headers, aligns, strict=True):
        pdf.cell(width, 7, _latin(header), border="B", align=align, fill=True)
    pdf.ln()

    pdf.set_font("Helvetica", "", 7.5)
    for index, item in enumerate(ctx["items"]):
        if pdf.get_y() > 260:
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 7.5)
            pdf.set_fill_color(226, 228, 230)
            for width, header, align in zip(widths, headers, aligns, strict=True):
                pdf.cell(width, 7, _latin(header), border="B", align=align, fill=True)
            pdf.ln()
            pdf.set_font("Helvetica", "", 7.5)
        fill = index % 2 == 1
        pdf.set_fill_color(250, 250, 250)
        values = (
            _SHORT_STATUS.get(item["status"], item["status"]),
            _bank_date(item) or "-",
            _bank_memo(item) or "-",
            _doc_label(item) or "-",
            (_due(item).split(" / ")[0][:5] if _due(item) else "-"),
            money(_bank_cents(item)),
            money(_doc_cents(item)),
            money(_difference(item)),
        )
        pdf.set_text_color(48, 53, 60)
        for width, value, align in zip(widths, values, aligns, strict=True):
            text = _clip(pdf, value, width - 2)
            pdf.cell(width, 6, text, border="B", align=align, fill=fill)
        pdf.ln()


def pdf_bytes(ctx: dict) -> bytes:
    org = ctx["org"]
    period = ctx["periodo"]
    subtitle = f"{org['name']} · CNPJ {format_document(org['cnpj'])}"
    if ctx.get("conta"):
        subtitle += f" · {ctx['conta']['label']}"
    if period.get("start"):
        subtitle += f" · {period['start']:%d/%m/%Y} a {period['end']:%d/%m/%Y}"
    pdf = _Document("Demonstrativo de conciliação", subtitle)
    pdf.add_page()
    _summary(pdf, ctx)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(15, 18, 21)
    pdf.cell(0, 6, "Lançamentos", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    _table(pdf, ctx)
    return bytes(pdf.output())


def filename(ctx: dict, extension: str) -> str:
    period = ctx["periodo"]
    if period.get("start"):
        stem = f"demonstrativo-{period['start']:%Y-%m}"
    else:
        stem = "demonstrativo-atual"
    if ctx.get("conta"):
        stem += f"-conta-{ctx['conta']['id']}"
    return f"{stem}.{extension}"
